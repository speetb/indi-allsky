import os
import sys
import io
import time
import math
import tempfile
import json
import subprocess
from datetime import datetime
from collections import OrderedDict
from pathlib import Path
import logging

import numpy
from astropy.io import fits

import ccdproc
from astropy.stats import mad_std

from multiprocessing import Queue
from multiprocessing import Value

from .exceptions import TimeOutException
from .exceptions import TemperatureException
from .exceptions import CameraException
from .exceptions import BadImage

from .config import IndiAllSkyConfig

from . import camera as camera_module

from . import constants

from .flask import create_app
from .flask import db
from .flask.miscDb import miscDb

#from .flask.models import TaskQueueState
#from .flask.models import TaskQueueQueue
from .flask.models import IndiAllSkyDbDarkFrameTable
from .flask.models import IndiAllSkyDbBadPixelMapTable
#from .flask.models import IndiAllSkyDbTaskQueueTable

from sqlalchemy.orm.exc import NoResultFound


try:
    import rawpy  # not available in all cases
except ImportError:
    rawpy = None


app = create_app()

logger = logging.getLogger('indi_allsky')


class IndiAllSkyDarks(object):

    def __init__(self):
        with app.app_context():
            try:
                self._config_obj = IndiAllSkyConfig()
            except NoResultFound:
                logger.error('No config file found, please import a config')
                sys.exit(1)

            self.config = self._config_obj.config

        self._daytime = True  # build daytime dark library

        self._count = 10
        self._temp_delta = 5.0
        self._time_delta = 5

        self._hotpixel_adu_percent = 90

        # this is used to set a max value of data returned by the camera
        self._bitmax = 0


        self.image_q = Queue()
        self.indiclient = None

        self.camera_id = None
        self.camera_name = None
        self.camera_server = None
        self.ccd_info = None

        self.exposure_v = Value('f', -1.0)
        self.gain_v = Value('i', -1)  # value set in CCD config
        self.bin_v = Value('i', 1)  # set 1 for sane default
        self.sensortemp_v = Value('f', 0)

        # not used, but required
        self.latitude_v = Value('f', float(self.config['LOCATION_LATITUDE']))
        self.longitude_v = Value('f', float(self.config['LOCATION_LONGITUDE']))
        self.ra_v = Value('f', 0.0)
        self.dec_v = Value('f', 0.0)

        self._miscDb = miscDb(self.config)


        if self.config['IMAGE_FOLDER']:
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()

        self.darks_dir = self.image_dir.joinpath('darks')


    @property
    def count(self):
        return self._count

    @count.setter
    def count(self, new_count):
        #logger.info('Changing image count to %d', int(new_count))
        self._count = int(new_count)


    @property
    def temp_delta(self):
        return self._temp_delta

    @temp_delta.setter
    def temp_delta(self, new_temp_delta):
        self._temp_delta = float(abs(new_temp_delta))


    @property
    def time_delta(self):
        return self._time_delta

    @time_delta.setter
    def time_delta(self, new_time_delta):
        self._time_delta = int(abs(new_time_delta))


    @property
    def bitmax(self):
        return self._bitmax

    @bitmax.setter
    def bitmax(self, new_bitmax):
        self._bitmax = int(new_bitmax)
        assert self._bitmax in (0, 8, 10, 12, 14, 16)


    @property
    def hotpixel_adu_percent(self):
        return self._hotpixel_adu_percent

    @hotpixel_adu_percent.setter
    def hotpixel_adu_percent(self, new_hotpixel_adu_percent):
        self._hotpixel_adu_percent = int(new_hotpixel_adu_percent)


    @property
    def daytime(self):
        return self._daytime

    @daytime.setter
    def daytime(self, new_daytime):
        self._daytime = bool(new_daytime)



    def _initialize(self):
        camera_interface = getattr(camera_module, self.config.get('CAMERA_INTERFACE', 'indi'))

        # instantiate the client
        self.indiclient = camera_interface(
            self.config,
            self.image_q,
            self.latitude_v,
            self.longitude_v,
            self.ra_v,
            self.dec_v,
            self.gain_v,
            self.bin_v,
        )

        # set indi server localhost and port
        self.indiclient.setServer(self.config['INDI_SERVER'], self.config['INDI_PORT'])

        # connect to indi server
        logger.info("Connecting to indiserver")
        if not self.indiclient.connectServer():
            logger.error("No indiserver running on %s:%d - Try to run", self.indiclient.getHost(), self.indiclient.getPort())
            logger.error("  indiserver indi_simulator_telescope indi_simulator_ccd")
            sys.exit(1)

        # give devices a chance to register
        time.sleep(8)


        try:
            self.indiclient.findCcd(camera_name=self.config.get('INDI_CAMERA_NAME'))
        except CameraException as e:
            logger.error('Camera error: %s', str(e))
            sys.exit(1)


        if not self.indiclient.ccd_device:
            logger.error('No CCDs detected')
            time.sleep(1)
            sys.exit(1)


        logger.warning('Connecting to device %s', self.indiclient.ccd_device.getDeviceName())
        self.indiclient.connectDevice(self.indiclient.ccd_device.getDeviceName())

        # add driver name to config
        self.camera_name = self.indiclient.ccd_device.getDeviceName()
        self.camera_server = self.indiclient.ccd_device.getDriverExec()


        # Get Properties
        ccd_properties = self.indiclient.getCcdDeviceProperties()
        self.config['CCD_PROPERTIES'] = ccd_properties


        # get CCD information
        ccd_info = self.indiclient.getCcdInfo()
        self.ccd_info = ccd_info


        if self.config.get('CFA_PATTERN'):
            cfa_pattern = self.config['CFA_PATTERN']
        else:
            cfa_pattern = ccd_info['CCD_CFA']['CFA_TYPE'].get('text')


        # need to get camera info before adding to DB
        camera_metadata = {
            'name'        : self.camera_name,

            'minExposure' : float(ccd_info.get('CCD_EXPOSURE', {}).get('CCD_EXPOSURE_VALUE', {}).get('min')),
            'maxExposure' : float(ccd_info.get('CCD_EXPOSURE', {}).get('CCD_EXPOSURE_VALUE', {}).get('max')),
            'minGain'     : int(ccd_info.get('GAIN_INFO', {}).get('min')),
            'maxGain'     : int(ccd_info.get('GAIN_INFO', {}).get('max')),
            'width'       : int(ccd_info.get('CCD_FRAME', {}).get('WIDTH', {}).get('max')),
            'height'      : int(ccd_info.get('CCD_FRAME', {}).get('HEIGHT', {}).get('max')),
            'bits'        : int(ccd_info.get('CCD_INFO', {}).get('CCD_BITSPERPIXEL', {}).get('current')),
            'pixelSize'   : float(ccd_info.get('CCD_INFO', {}).get('CCD_PIXEL_SIZE', {}).get('current')),
            'cfa'         : constants.CFA_STR_MAP[cfa_pattern],

            'location'    : self.config['LOCATION_NAME'],
            'latitude'    : self.latitude_v.value,
            'longitude'   : self.longitude_v.value,

            'lensName'        : self.config['LENS_NAME'],
            'lensFocalLength' : self.config['LENS_FOCAL_LENGTH'],
            'lensFocalRatio'  : self.config['LENS_FOCAL_RATIO'],
            'alt'             : self.config['LENS_ALTITUDE'],
            'az'              : self.config['LENS_AZIMUTH'],
            'nightSunAlt'     : self.config['NIGHT_SUN_ALT_DEG'],
        }

        db_camera = self._miscDb.addCamera(camera_metadata)
        self.camera_id = db_camera.id

        try:
            # Disable debugging
            self.indiclient.disableDebugCcd()
        except TimeOutException:
            logger.warning('Camera does not support debug')

        # set BLOB mode to BLOB_ALSO
        self.indiclient.updateCcdBlobMode()

        self.indiclient.configureCcdDevice(self.config['INDI_CONFIG_DEFAULTS'])


        try:
            self.indiclient.setCcdFrameType('FRAME_DARK')
        except TimeOutException:
            # this is an optional step
            # occasionally the CCD_FRAME_TYPE property is not available during initialization
            logger.warning('Unable to set CCD_FRAME_TYPE to Dark')


        # Validate gain settings
        ccd_min_gain = ccd_info['GAIN_INFO']['min']
        ccd_max_gain = ccd_info['GAIN_INFO']['max']

        if self.config['CCD_CONFIG']['NIGHT']['GAIN'] < ccd_min_gain:
            logger.error('CCD night gain below minimum, changing to %d', int(ccd_min_gain))
            self.config['CCD_CONFIG']['NIGHT']['GAIN'] = int(ccd_min_gain)
            time.sleep(3)
        elif self.config['CCD_CONFIG']['NIGHT']['GAIN'] > ccd_max_gain:
            logger.error('CCD night gain above maximum, changing to %d', int(ccd_max_gain))
            self.config['CCD_CONFIG']['NIGHT']['GAIN'] = int(ccd_max_gain)
            time.sleep(3)

        if self.config['CCD_CONFIG']['MOONMODE']['GAIN'] < ccd_min_gain:
            logger.error('CCD moon mode gain below minimum, changing to %d', int(ccd_min_gain))
            self.config['CCD_CONFIG']['MOONMODE']['GAIN'] = int(ccd_min_gain)
            time.sleep(3)
        elif self.config['CCD_CONFIG']['MOONMODE']['GAIN'] > ccd_max_gain:
            logger.error('CCD moon mode gain above maximum, changing to %d', int(ccd_max_gain))
            self.config['CCD_CONFIG']['MOONMODE']['GAIN'] = int(ccd_max_gain)
            time.sleep(3)

        if self.config['CCD_CONFIG']['DAY']['GAIN'] < ccd_min_gain:
            logger.error('CCD day gain below minimum, changing to %d', int(ccd_min_gain))
            self.config['CCD_CONFIG']['DAY']['GAIN'] = int(ccd_min_gain)
            time.sleep(3)
        elif self.config['CCD_CONFIG']['DAY']['GAIN'] > ccd_max_gain:
            logger.error('CCD day gain above maximum, changing to %d', int(ccd_max_gain))
            self.config['CCD_CONFIG']['DAY']['GAIN'] = int(ccd_max_gain)
            time.sleep(3)


    def shoot(self, exposure, sync=True, timeout=None):
        logger.info('Taking %0.8f s exposure (gain %d)', exposure, self.gain_v.value)

        self.indiclient.setCcdExposure(exposure, sync=sync, timeout=timeout)


    def _wait_for_image(self, exposure):
        i_dict = self.image_q.get(timeout=10)

        ### Not using DB task queue for image processing to reduce database I/O
        #task_id = i_dict['task_id']

        #try:
        #    task = IndiAllSkyDbTaskQueueTable.query\
        #        .filter(IndiAllSkyDbTaskQueueTable.id == task_id)\
        #        .filter(IndiAllSkyDbTaskQueueTable.state == TaskQueueState.QUEUED)\
        #        .filter(IndiAllSkyDbTaskQueueTable.queue == TaskQueueQueue.IMAGE)\
        #        .one()

        #except NoResultFound:
        #    logger.error('Task ID %d not found', task_id)
        #    raise


        # go ahead and set complete
        #task.setSuccess('Dark frame processed')

        #filename = Path(task.data['filename'])
        ###


        filename_p = Path(i_dict['filename'])

        if not filename_p.exists():
            #task.setFailed('Frame not found: {0:s}'.format(str(filename_p)))
            raise Exception('Frame not found {0:s}'.format(str(filename_p)))


        if filename_p.stat().st_size == 0:
            #task.setFailed('Frame is empty: {0:s}'.format(str(filename_p)))
            raise Exception('Frame is empty: {0:s}'.format(str(filename_p)))



        ### Open file
        if filename_p.suffix in ['.fit']:
            try:
                hdulist = fits.open(filename_p)
            except OSError as e:
                filename_p.unlink()
                raise BadImage(str(e)) from e
        elif filename_p.suffix in ['.dng']:
            if not rawpy:
                filename_p.unlink()
                raise Exception('*** rawpy module not available ***')

            # DNG raw
            try:
                raw = rawpy.imread(str(filename_p))
            except rawpy._rawpy.LibRawIOError as e:
                filename_p.unlink()
                raise BadImage(str(e)) from e

            scidata_uncalibrated = raw.raw_image

            # create a new fits container for DNG data
            hdu = fits.PrimaryHDU(scidata_uncalibrated)
            hdulist = fits.HDUList([hdu])

            hdulist[0].header['IMAGETYP'] = 'Dark Frame'
            hdulist[0].header['INSTRUME'] = 'libcamera'
            hdulist[0].header['EXPTIME'] = float(exposure)
            hdulist[0].header['XBINNING'] = 1
            hdulist[0].header['YBINNING'] = 1
            hdulist[0].header['GAIN'] = float(self.gain_v.value)
            hdulist[0].header['CCD-TEMP'] = self.sensortemp_v.value
            hdulist[0].header['BITPIX'] = 16

            if self.config.get('CFA_PATTERN'):
                hdulist[0].header['BAYERPAT'] = self.config['CFA_PATTERN']
                hdulist[0].header['XBAYROFF'] = 0
                hdulist[0].header['YBAYROFF'] = 0
            elif self.ccd_info['CCD_CFA']['CFA_TYPE'].get('text'):
                hdulist[0].header['BAYERPAT'] = self.ccd_info['CCD_CFA']['CFA_TYPE']['text']
                hdulist[0].header['XBAYROFF'] = 0
                hdulist[0].header['YBAYROFF'] = 0

            #for h in hdulist[0].header.keys():
            #    logger.info('  Header: %s = %s', h, str(hdulist[0].header[h]))
        else:
            raise Exception('Dark frames only supported with raw formats (fits, dng)')


        filename_p.unlink()  # no longer need the original file


        return hdulist



    def average(self):
        with app.app_context():
            self._average()


    def _average(self):
        self._initialize()
        self._pre_run_tasks()

        self._run(IndiAllSkyDarksAverage)


    def tempaverage(self):
        with app.app_context():
            self._tempaverage()


    def _tempaverage(self):
        # disable daytime darks processing when doing temperature calibrated frames
        self.daytime = False

        self._initialize()

        self._pre_run_tasks()

        current_temp = self.getSensorTemperature()
        next_temp_thold = current_temp - self._temp_delta

        # get first set of images
        self._run(IndiAllSkyDarksAverage)

        while True:
            # This loop will run forever, it is up to the user to cancel
            current_temp = self.getSensorTemperature()

            logger.info('Next temperature threshold: %0.1f', next_temp_thold)

            if current_temp > next_temp_thold:
                time.sleep(20.0)
                continue

            logger.warning('Acheived next temperature threshold')
            next_temp_thold = next_temp_thold - self._temp_delta

            self._run(IndiAllSkyDarksAverage)



    def sigmaclip(self):
        with app.app_context():
            self._sigmaclip()


    def _sigmaclip(self):
        self._initialize()
        self._pre_run_tasks()

        self._run(IndiAllSkyDarksSigmaClip)


    def tempsigmaclip(self):
        with app.app_context():
            self._tempsigmaclip()


    def _tempsigmaclip(self):
        # disable daytime darks processing when doing temperature calibrated frames
        self.daytime = False

        self._initialize()

        self._pre_run_tasks()

        current_temp = self.getSensorTemperature()
        next_temp_thold = current_temp - self._temp_delta

        # get first set of images
        self._run(IndiAllSkyDarksSigmaClip)

        while True:
            # This loop will run forever, it is up to the user to cancel
            current_temp = self.getSensorTemperature()

            logger.info('Next temperature threshold: %0.1f', next_temp_thold)

            if current_temp > next_temp_thold:
                time.sleep(20.0)
                continue

            logger.warning('Acheived next temperature threshold')
            next_temp_thold = next_temp_thold - self._temp_delta

            self._run(IndiAllSkyDarksSigmaClip)


    def _pre_run_tasks(self):
        # Tasks that need to be run before the main program loop

        if self.camera_server in ['indi_rpicam']:
            # Raspberry PI HQ Camera requires an initial throw away exposure of over 6s
            # in order to take exposures longer than 7s
            logger.info('Taking throw away exposure for rpicam')
            self.shoot(7.0, sync=True, timeout=20.0)


            i_dict = self.image_q.get(timeout=10)

            ### Not using DB task queue for image processing to reduce database I/O
            #task_id = i_dict['task_id']

            #try:
            #    task = IndiAllSkyDbTaskQueueTable.query\
            #        .filter(IndiAllSkyDbTaskQueueTable.id == task_id)\
            #        .filter(IndiAllSkyDbTaskQueueTable.state == TaskQueueState.QUEUED)\
            #        .filter(IndiAllSkyDbTaskQueueTable.queue == TaskQueueQueue.IMAGE)\
            #        .one()

            #except NoResultFound:
            #    logger.error('Task ID %d not found', task_id)
            #    raise


            ### go ahead and set complete
            #task.setSuccess('Throw away frame')

            #filename = Path(task.data['filename'])
            ###


            filename = Path(i_dict['filename'])

            if not filename.exists():
                #task.setFailed('Frame not found: {0:s}'.format(str(filename)))
                raise Exception('Frame not found {0:s}'.format(str(filename)))


            filename.unlink()  # no longer need the original file


    def _pre_shoot_reconfigure(self):
        if self.camera_server in ['indi_asi_ccd']:
            # There is a bug in the ASI120M* camera that causes exposures to fail on gain changes
            # The indi_asi_ccd server will switch the camera to 8-bit mode to try to correct
            if self.camera_name.startswith('ZWO CCD ASI120'):
                self.indiclient.configureCcdDevice(self.config['INDI_CONFIG_DEFAULTS'])
        elif self.camera_server in ['indi_asi_single_ccd']:
            if self.camera_name.startswith('ZWO ASI120'):
                self.indiclient.configureCcdDevice(self.config['INDI_CONFIG_DEFAULTS'])


    def _run(self, stacking_class):

        ccd_bits = int(self.ccd_info['CCD_INFO']['CCD_BITSPERPIXEL']['current'])


        # exposures start with 1 and then every 5s until the max exposure
        dark_exposures = [1]
        dark_exposures.extend(
            list(
                range(
                    self._time_delta,
                    math.ceil(self.config['CCD_EXPOSURE_MAX'] / self._time_delta) * self._time_delta,
                    self._time_delta,
                )
            )
        )
        dark_exposures.append(math.ceil(self.config['CCD_EXPOSURE_MAX']))  # round up
        dark_exposures.reverse()  # take longer exposures first


        bpm_filename_t = 'bpm_ccd{0:d}_{1:d}bit_{2:d}s_gain{3:d}_bin{4:d}_{5:d}c_{6:s}.fit'
        dark_filename_t = 'dark_ccd{0:d}_{1:d}bit_{2:d}s_gain{3:d}_bin{4:d}_{5:d}c_{6:s}.fit'
        # 0  = ccd id
        # 1  = bits
        # 2  = exposure (seconds)
        # 3  = gain
        # 4  = binning
        # 5  = temperature
        # 6  = date
        # 7  = extension


        night_darks_odict = OrderedDict()  # using OrderedDict as a pseudo-set, we only care about keys
        # keys are a tuple of (gain, binmode)

        # if NIGHT and MOONMODE have the same parameters, no need to double the work
        night_darks_odict.update(
            {
                (self.config['CCD_CONFIG']['NIGHT']['GAIN'], self.config['CCD_CONFIG']['NIGHT']['BINNING']) : None,
            }
        )
        night_darks_odict.update(
            {
                (self.config['CCD_CONFIG']['MOONMODE']['GAIN'], self.config['CCD_CONFIG']['MOONMODE']['BINNING']) : None,
            }
        )


        ### take darks


        # take day darks with cooling disabled
        if self.daytime:
            self.indiclient.disableCcdCooler()
            logger.warning('****** IF THE CCD COOLER WAS ENABLED, YOU MAY CONSIDER STOPPING THIS UNTIL THE SENSOR HAS WARMED ******')
            time.sleep(8.0)


            ### DAY DARKS ###
            day_params = (self.config['CCD_CONFIG']['DAY']['GAIN'], self.config['CCD_CONFIG']['DAY']['BINNING'])
            if day_params not in night_darks_odict.keys():
                self.indiclient.setCcdGain(self.config['CCD_CONFIG']['DAY']['GAIN'])
                self.indiclient.setCcdBinning(self.config['CCD_CONFIG']['DAY']['BINNING'])

                # day will rarely exceed 1 second
                for exposure in dark_exposures:
                    self._take_exposures(exposure, dark_filename_t, bpm_filename_t, ccd_bits, stacking_class)
        else:
            logger.warning('Daytime dark processing is disabled')
            time.sleep(8.0)



        # take night darks with cooling enabled
        if self.config.get('CCD_COOLING'):
            ccd_temp = self.config.get('CCD_TEMP', 15.0)
            self.indiclient.enableCcdCooler()
            logger.warning('****** WAITING UP TO 20 MINUTES FOR TARGET TEMPERATURE ******')
            self.indiclient.setCcdTemperature(ccd_temp, sync=True, timeout=1200.0)


        ### NIGHT DARKS ###
        for gain, binmode in night_darks_odict.keys():
            self.indiclient.setCcdGain(gain)
            self.indiclient.setCcdBinning(binmode)

            for exposure in dark_exposures:
                self._take_exposures(exposure, dark_filename_t, bpm_filename_t, ccd_bits, stacking_class)



        # shutdown
        self.indiclient.disableCcdCooler()
        self.indiclient.disconnectServer()



    def _take_exposures(self, exposure, dark_filename_t, bpm_filename_t, ccd_bits, stacking_class):
        exposure_f = float(exposure)

        tmp_fit_dir = tempfile.TemporaryDirectory()
        tmp_fit_dir_p = Path(tmp_fit_dir.name)

        logger.info('Temp folder: %s', tmp_fit_dir_p)

        image_bitpix = None

        i = 1
        while i <= self._count:
            # sometimes image data is bad, take images until we reach the desired number
            start = time.time()

            self._pre_shoot_reconfigure()

            self.shoot(exposure_f, sync=True, timeout=180.0)  # flat 3 minute timeout

            elapsed_s = time.time() - start

            logger.info('Exposure received in %0.4f s', elapsed_s)


            try:
                hdulist = self._wait_for_image(exposure_f)
            except BadImage as e:
                logger.error('Bad Image: %s', str(e))
                continue


            hdulist[0].header['BUNIT'] = 'ADU'  # hack for ccdproc

            image_bitpix = hdulist[0].header['BITPIX']

            f_tmp_fit = tempfile.NamedTemporaryFile(dir=tmp_fit_dir_p, suffix='.fit', delete=False)
            hdulist.writeto(f_tmp_fit)
            f_tmp_fit.flush()
            f_tmp_fit.close()

            #logger.info('FIT: %s', f_tmp_fit.name)

            m_avg = numpy.mean(hdulist[0].data, axis=1)[0]
            logger.info('Image average adu: %0.2f', m_avg)

            self.getSensorTemperature()
            logger.info('Sensor temperature: %0.2f', self.sensortemp_v.value)

            i += 1  # increment


        # libcamera does not know the temperature until the first exposure is taken
        exp_date = datetime.now()
        date_str = exp_date.strftime('%Y%m%d_%H%M%S')
        dark_filename = dark_filename_t.format(
            self.camera_id,
            ccd_bits,
            int(exposure),
            self.gain_v.value,
            self.bin_v.value,
            int(self.sensortemp_v.value),
            date_str,
        )
        bpm_filename = bpm_filename_t.format(
            self.camera_id,
            ccd_bits,
            int(exposure),
            self.gain_v.value,
            self.bin_v.value,
            int(self.sensortemp_v.value),
            date_str,
        )

        full_dark_filename_p = self.darks_dir.joinpath(dark_filename)
        full_bpm_filename_p = self.darks_dir.joinpath(bpm_filename)


        s = stacking_class(self.gain_v, self.bin_v)
        s.bitmax = self._bitmax
        s.hotpixel_adu_percent = self._hotpixel_adu_percent

        s.buildBadPixelMap(tmp_fit_dir_p, full_bpm_filename_p, exposure_f, image_bitpix)
        s.stack(tmp_fit_dir_p, full_dark_filename_p, exposure_f, image_bitpix)

        dark_metadata = {
            'type'       : constants.DARK_FRAME,
            'createDate' : exp_date.timestamp(),
            'bitdepth'   : image_bitpix,
            'exposure'   : exposure_f,
            'gain'       : self.gain_v.value,
            'binmode'    : self.bin_v.value,
            'temp'       : self.sensortemp_v.value,
        }

        bpm_metadata = {
            'type'       : constants.BPM_FRAME,
            'createDate' : exp_date.timestamp(),
            'bitdepth'   : image_bitpix,
            'exposure'   : exposure_f,
            'gain'       : self.gain_v.value,
            'binmode'    : self.bin_v.value,
            'temp'       : self.sensortemp_v.value,
        }


        self._miscDb.addBadPixelMap(
            full_bpm_filename_p,
            self.camera_id,
            dark_metadata,
        )

        self._miscDb.addDarkFrame(
            full_dark_filename_p,
            self.camera_id,
            bpm_metadata,
        )

        tmp_fit_dir.cleanup()



    def flush(self):
        with app.app_context():
            self._flush()


    def _flush(self):
        badpixelmaps_all = IndiAllSkyDbBadPixelMapTable.query
        dark_frames_all = IndiAllSkyDbDarkFrameTable.query

        logger.warning('Found %d bad pixel maps to flush', badpixelmaps_all.count())
        logger.warning('Found %d dark frames to flush', dark_frames_all.count())
        logger.warning('Flushing in 10 seconds...')

        time.sleep(10.0)

        for bpm_entry in badpixelmaps_all:
            filename = Path(bpm_entry.filename)

            if filename.exists():
                logger.warning('Removing bad pixel map: %s', filename)
                filename.unlink()

        for dark_frame_entry in dark_frames_all:
            filename = Path(dark_frame_entry.filename)

            if filename.exists():
                logger.warning('Removing dark frame: %s', filename)
                filename.unlink()


        badpixelmaps_all.delete()
        dark_frames_all.delete()
        db.session.commit()



    def getSensorTemperature(self):
        temp_val = self.indiclient.getCcdTemperature()


        # query external temperature if camera does not return temperature
        if temp_val < -100.0 and self.config.get('CCD_TEMP_SCRIPT'):
            try:
                ext_temp_val = self.getExternalTemperature(self.config.get('CCD_TEMP_SCRIPT'))
                temp_val = ext_temp_val
            except TemperatureException as e:
                logger.error('Exception querying external temperature: %s', str(e))


        temp_val_f = float(temp_val)

        with self.sensortemp_v.get_lock():
            self.sensortemp_v.value = temp_val_f


        return temp_val_f


    def getExternalTemperature(self, script_path):
        temp_script_p = Path(script_path)

        logger.info('Running external script for temperature: %s', temp_script_p)

        # need to be extra careful running in the main thread
        if not temp_script_p.exists():
            raise TemperatureException('Temperature script does not exist')

        if not temp_script_p.is_file():
            raise TemperatureException('Temperature script is not a file')

        if temp_script_p.stat().st_size == 0:
            raise TemperatureException('Temperature script is empty')

        if not os.access(str(temp_script_p), os.X_OK):
            raise TemperatureException('Temperature script is not executable')


        # generate a tempfile for the data
        f_tmp_tempjson = tempfile.NamedTemporaryFile(mode='w', delete=True, suffix='.json')
        f_tmp_tempjson.close()

        tempjson_name_p = Path(f_tmp_tempjson.name)


        cmd = [
            str(temp_script_p),
        ]


        # the file used for the json data is communicated via environment variable
        cmd_env = {
            'TEMP_JSON' : str(tempjson_name_p),
        }


        try:
            temp_process = subprocess.Popen(
                cmd,
                env=cmd_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            raise TemperatureException('Temperature script failed to execute')


        try:
            temp_process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            temp_process.kill()
            time.sleep(1.0)
            temp_process.poll()  # close out process
            raise TemperatureException('Temperature script timed out')


        if temp_process.returncode != 0:
            raise TemperatureException('Temperature script returned exited abnormally')


        try:
            with io.open(str(tempjson_name_p), 'r') as tempjson_name_f:
                temp_data = json.load(tempjson_name_f)

            tempjson_name_p.unlink()  # remove temp file
        except PermissionError as e:
            logger.error(str(e))
            raise TemperatureException(str(e))
        except json.JSONDecodeError as e:
            logger.error('Error decoding json: %s', str(e))
            raise TemperatureException(str(e))
        except FileNotFoundError as e:
            raise TemperatureException(str(e))


        try:
            temp_float = float(temp_data['temp'])
        except ValueError:
            raise TemperatureException('Temperature script returned a non-numerical value')
        except KeyError:
            raise TemperatureException('Temperature script returned incorrect data')


        return temp_float



class IndiAllSkyDarksProcessor(object):
    def __init__(self, gain_v, bin_v):
        self.gain_v = gain_v
        self.bin_v = bin_v

        self._hotpixel_adu_percent = 90

        self._bitmax = 0


    @property
    def bitmax(self):
        return self._bitmax

    @bitmax.setter
    def bitmax(self, new_bitmax):
        self._bitmax = int(new_bitmax)


    @property
    def hotpixel_adu_percent(self):
        return self._hotpixel_adu_percent

    @hotpixel_adu_percent.setter
    def hotpixel_adu_percent(self, new_hotpixel_adu_percent):
        self._hotpixel_adu_percent = int(new_hotpixel_adu_percent)



    def buildBadPixelMap(self, tmp_fit_dir_p, filename_p, exposure, image_bitpix):
        logger.info('Building bad pixel map for exposure %0.1fs, gain %d, bin %d', exposure, self.gain_v.value, self.bin_v.value)

        if image_bitpix == 16:
            numpy_type = numpy.uint16
        elif image_bitpix == 8:
            numpy_type = numpy.uint8
        else:
            raise Exception('Unknown bits per pixel')


        image_data = list()
        hdulist = None
        for item in Path(tmp_fit_dir_p).iterdir():
            #logger.info('Found item: %s', item)
            if item.is_file() and item.suffix in ['.fit']:
                #logger.info('Found fit: %s', item)
                hdulist = fits.open(item)
                image_data.append(hdulist[0].data)


        image_height, image_width = image_data[0].shape[:2]
        bpm = numpy.zeros((image_height, image_width), dtype=numpy_type)

        # take the max values of each pixel from each image
        for image in image_data:
            bpm = numpy.maximum(bpm, image)


        max_val = numpy.amax(bpm)
        logger.info('Image max value: %d', int(max_val))

        if self._bitmax:
            bitmax_percent = (2 ** self._bitmax) * (self._hotpixel_adu_percent / 100.0)
        else:
            bitmax_percent = (2 ** image_bitpix) * (self._hotpixel_adu_percent / 100.0)

        bpm[bpm < bitmax_percent] = 0  # filter all values less than max value

        hdulist[0].data = bpm

        # reuse the last fits file for the stacked data
        hdulist.writeto(filename_p)


    def stack(self, tmp_fit_dir_p, filename_p, exposure, image_bitpix):
        raise Exception('Must be redefined in sub-class')


class IndiAllSkyDarksAverage(IndiAllSkyDarksProcessor):
    def stack(self, tmp_fit_dir_p, filename_p, exposure, image_bitpix):
        logger.info('Stacking dark frames for exposure %0.1fs, gain %d, bin %d', exposure, self.gain_v.value, self.bin_v.value)

        if image_bitpix == 16:
            numpy_type = numpy.uint16
        elif image_bitpix == 8:
            numpy_type = numpy.uint8
        else:
            raise Exception('Unknown bits per pixel')

        image_data = list()
        hdulist = None
        for item in Path(tmp_fit_dir_p).iterdir():
            #logger.info('Found item: %s', item)
            if item.is_file() and item.suffix in ('.fit',):
                #logger.info('Found fit: %s', item)
                hdulist = fits.open(item)
                image_data.append(hdulist[0].data)


        start = time.time()

        avg_image = numpy.mean(image_data, axis=0)
        data = numpy.floor(avg_image).astype(numpy_type)  # no floats

        elapsed_s = time.time() - start
        logger.info('Exposure average stacked in %0.4f s', elapsed_s)


        hdulist[0].data = data

        # reuse the last fits file for the stacked data
        hdulist.writeto(filename_p)



class IndiAllSkyDarksSigmaClip(IndiAllSkyDarksProcessor):
    def stack(self, tmp_fit_dir_p, filename_p, exposure, image_bitpix):
        logger.info('Stacking dark frames for exposure %0.1fs, gain %d, bin %d', exposure, self.gain_v.value, self.bin_v.value)

        if image_bitpix == 16:
            numpy_type = numpy.uint16
        elif image_bitpix == 8:
            numpy_type = numpy.uint8

        dark_images = ccdproc.ImageFileCollection(tmp_fit_dir_p)

        cal_darks = dark_images.files_filtered(exptime=exposure, include_path=True)


        start = time.time()

        combined_dark = ccdproc.combine(
            cal_darks,
            method='average',
            sigma_clip=True,
            sigma_clip_low_thresh=5,
            sigma_clip_high_thresh=5,
            sigma_clip_func=numpy.ma.median,
            signma_clip_dev_func=mad_std,
            dtype=numpy_type,
            mem_limit=350000000,
        )

        elapsed_s = time.time() - start
        logger.info('Exposure sigma clip stacked in %0.4f s', elapsed_s)


        combined_dark.meta['combined'] = True

        combined_dark.write(filename_p)

