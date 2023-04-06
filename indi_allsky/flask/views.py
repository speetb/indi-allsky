import platform
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import io
import json
import time
import math
import base64
from pathlib import Path
import socket
import re
import psutil
import dbus
import pycurl
import paramiko
import paho.mqtt
import ccdproc

import ephem

from passlib.hash import argon2

# for version reporting
import PyIndi
import cv2
import numpy
import astropy
import flask

from ..version import __version__

from flask import request
from flask import session
from flask import jsonify
from flask import Blueprint
from flask import redirect
from flask import url_for
from flask import send_from_directory
from flask import current_app as app

from flask_login import login_required
from flask_login import current_user

from . import db

from .models import IndiAllSkyDbCameraTable
from .models import IndiAllSkyDbImageTable
from .models import IndiAllSkyDbVideoTable
from .models import IndiAllSkyDbKeogramTable
from .models import IndiAllSkyDbStarTrailsTable
from .models import IndiAllSkyDbStarTrailsVideoTable
from .models import IndiAllSkyDbDarkFrameTable
from .models import IndiAllSkyDbBadPixelMapTable
from .models import IndiAllSkyDbRawImageTable
from .models import IndiAllSkyDbFitsImageTable
from .models import IndiAllSkyDbTaskQueueTable
from .models import IndiAllSkyDbNotificationTable
from .models import IndiAllSkyDbUserTable
from .models import IndiAllSkyDbConfigTable

from .models import TaskQueueQueue
from .models import TaskQueueState

from sqlalchemy import func
from sqlalchemy import extract
from sqlalchemy import cast
from sqlalchemy import and_
from sqlalchemy import or_
#from sqlalchemy.types import DateTime
from sqlalchemy.types import Integer
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql.expression import true as sa_true
from sqlalchemy.sql.expression import false as sa_false
from sqlalchemy.sql.expression import null as sa_null

from .forms import IndiAllskyConfigForm
from .forms import IndiAllskyImageViewer
from .forms import IndiAllskyImageViewerPreload
from .forms import IndiAllskyVideoViewer
from .forms import IndiAllskyVideoViewerPreload
from .forms import IndiAllskySystemInfoForm
from .forms import IndiAllskyHistoryForm
from .forms import IndiAllskySetDateTimeForm
from .forms import IndiAllskyTimelapseGeneratorForm
from .forms import IndiAllskyFocusForm
from .forms import IndiAllskyLogViewerForm
from .forms import IndiAllskyUserInfoForm

from .base_views import BaseView
from .base_views import TemplateView
from .base_views import FormView
from .base_views import JsonView

from ..exceptions import ConfigSaveException


bp_allsky = Blueprint(
    'indi_allsky',
    __name__,
    template_folder='templates',
    static_folder='static',
    #url_prefix='/',  # wsgi
    url_prefix='/indi-allsky',  # gunicorn
    static_url_path='static',
)


class IndexView(TemplateView):
    def get_context(self):
        context = super(IndexView, self).get_context()

        refreshInterval_ms = math.ceil(self.indi_allsky_config.get('CCD_EXPOSURE_MAX', 15.0) * 1000)
        context['refreshInterval'] = refreshInterval_ms

        return context


class JsonLatestImageView(JsonView):
    def __init__(self, **kwargs):
        super(JsonLatestImageView, self).__init__(**kwargs)

        self.history_seconds = 900


    def get_objects(self):
        history_seconds = int(request.args.get('limit_s', self.history_seconds))
        night = bool(int(request.args.get('night', 1)))

        # sanity check
        if history_seconds > 86400:
            history_seconds = 86400


        data = {
            'latest_image' : {
                'url' : None,
            },
        }


        if self.indi_allsky_config.get('FOCUS_MODE', False):
            latest_image_uri = Path('images/latest.{0}'.format(self.indi_allsky_config.get('IMAGE_FILE_TYPE', 'jpg')))

            image_dir = Path(self.indi_allsky_config['IMAGE_FOLDER']).absolute()
            latest_image_p = image_dir.joinpath(latest_image_uri.name)

            if latest_image_p.exists():
                # use latest image if it exists
                max_age = datetime.now() - timedelta(seconds=history_seconds)
                if latest_image_p.stat().st_mtime > max_age.timestamp():

                    data['latest_image']['url'] = '{0:s}?{1:d}'.format(str(latest_image_uri), int(time.time()))
                    return data
                else:
                    return data
            else:
                return data


        if not night:
            if self.indi_allsky_config['DAYTIME_CAPTURE'] and not self.indi_allsky_config['DAYTIME_TIMELAPSE']:
                # images are not stored in the DB in this condition
                latest_image_uri = Path('images/latest.{0}'.format(self.indi_allsky_config.get('IMAGE_FILE_TYPE', 'jpg')))

                image_dir = Path(self.indi_allsky_config['IMAGE_FOLDER']).absolute()
                latest_image_p = image_dir.joinpath(latest_image_uri.name)

                if latest_image_p.exists():
                    # use latest image if it exists
                    max_age = datetime.now() - timedelta(seconds=history_seconds)
                    if latest_image_p.stat().st_mtime > max_age.timestamp():

                        data['latest_image']['url'] = '{0:s}?{1:d}'.format(str(latest_image_uri), int(time.time()))
                        return data
                    else:
                        return data
                else:
                    return data


        # use database
        data['latest_image']['url'] = self.getLatestImage(session['camera_id'], history_seconds)

        return data


    def getLatestImage(self, camera_id, history_seconds):
        now_minus_seconds = datetime.now() - timedelta(seconds=history_seconds)

        latest_image_q = IndiAllSkyDbImageTable.query\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == camera_id,
                    IndiAllSkyDbImageTable.createDate > now_minus_seconds,
                )
            )


        if self.indi_allsky_config.get('WEB_NONLOCAL_IMAGES'):
            # Do not serve local assets
            latest_image_q = latest_image_q\
                .filter(
                    or_(
                        IndiAllSkyDbImageTable.remote_url != sa_null(),
                        IndiAllSkyDbImageTable.s3_key != sa_null(),
                    )
                )


        latest_image = latest_image_q\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())\
            .first()


        if not latest_image:
            return None


        try:
            url = latest_image.getUrl(s3_prefix=self.s3_prefix)
        except ValueError as e:
            app.logger.error('Error determining relative file name: %s', str(e))
            return None


        return str(url)


class PublicIndexView(BaseView):
    # Legacy redirect
    def dispatch_request(self):
        return redirect(url_for('indi_allsky.index_view'))


class CamerasView(TemplateView):
    def get_context(self):
        context = super(CamerasView, self).get_context()

        context['camera_list'] = IndiAllSkyDbCameraTable.query\
            .all()

        return context


class DarkFramesView(TemplateView):
    def get_context(self):
        context = super(DarkFramesView, self).get_context()

        darkframe_list = IndiAllSkyDbDarkFrameTable.query\
            .join(IndiAllSkyDbCameraTable)\
            .order_by(
                IndiAllSkyDbCameraTable.id.desc(),
                IndiAllSkyDbDarkFrameTable.gain.asc(),
                IndiAllSkyDbDarkFrameTable.exposure.asc(),
            )

        bpm_list = IndiAllSkyDbBadPixelMapTable.query\
            .join(IndiAllSkyDbCameraTable)\
            .order_by(
                IndiAllSkyDbCameraTable.id.desc(),
                IndiAllSkyDbBadPixelMapTable.gain.asc(),
                IndiAllSkyDbBadPixelMapTable.exposure.asc(),
            )


        context['darkframe_list'] = darkframe_list
        context['bpm_list'] = bpm_list

        return context



class ImageLagView(TemplateView):
    def get_context(self):
        context = super(ImageLagView, self).get_context()

        now_minus_3h = datetime.now() - timedelta(hours=3)


        if app.config['SQLALCHEMY_DATABASE_URI'].startswith('mysql'):
            createDate_s = func.date_format('%s', IndiAllSkyDbImageTable.createDate)  # mysql
        elif app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgresql'):
            createDate_s = func.to_char(IndiAllSkyDbImageTable.createDate, '%s')  # postgres
        else:
            # assume sqlite
            createDate_s = func.strftime('%s', IndiAllSkyDbImageTable.createDate)  # sqlite


        image_lag_list = IndiAllSkyDbImageTable.query\
            .add_columns(
                IndiAllSkyDbImageTable.id,
                IndiAllSkyDbImageTable.createDate,
                IndiAllSkyDbImageTable.exposure,
                IndiAllSkyDbImageTable.exp_elapsed,
                IndiAllSkyDbImageTable.process_elapsed,
                (cast(createDate_s, Integer) - func.lag(createDate_s).over(order_by=IndiAllSkyDbImageTable.createDate)).label('lag_diff'),
            )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == session['camera_id'],
                    IndiAllSkyDbImageTable.createDate > now_minus_3h,
                )
            )\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())\
            .limit(50)
        # filter is just to make it faster


        context['image_lag_list'] = image_lag_list

        return context


class RollingAduView(TemplateView):
    def get_context(self):
        context = super(RollingAduView, self).get_context()

        now_minus_3d = datetime.now() - timedelta(days=3)
        createDate_hour = extract('hour', IndiAllSkyDbImageTable.createDate).label('createDate_hour')


        if app.config['SQLALCHEMY_DATABASE_URI'].startswith('mysql'):
            createDate_s = func.date_format('%s', IndiAllSkyDbImageTable.createDate)  # mysql
        elif app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgresql'):
            createDate_s = func.to_char(IndiAllSkyDbImageTable.createDate, '%s')  # postgres
        else:
            # assume sqlite
            createDate_s = func.strftime('%s', IndiAllSkyDbImageTable.createDate)  # sqlite


        # this should give us average exposure, adu in 15 minute sets, during the night
        rolling_adu_list = IndiAllSkyDbImageTable.query\
            .add_columns(
                IndiAllSkyDbImageTable.createDate.label('dt'),
                func.count(IndiAllSkyDbImageTable.id).label('i_count'),
                func.avg(IndiAllSkyDbImageTable.exposure).label('exposure_avg'),
                func.avg(IndiAllSkyDbImageTable.adu).label('adu_avg'),
                func.avg(IndiAllSkyDbImageTable.sqm).label('sqm_avg'),
                func.avg(IndiAllSkyDbImageTable.stars).label('stars_avg'),
            )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == session['camera_id'])\
            .filter(
                and_(
                    IndiAllSkyDbImageTable.createDate > now_minus_3d,
                    or_(
                        createDate_hour >= 22,  # night is normally between 10p and 4a, right?
                        createDate_hour <= 4,
                    )
                )
            )\
            .group_by(cast(createDate_s, Integer) / 900)\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())


        context['rolling_adu_list'] = rolling_adu_list

        return context


class SqmView(TemplateView):
    def get_context(self):
        context = super(SqmView, self).get_context()

        refreshInterval_ms = math.ceil(self.indi_allsky_config.get('CCD_EXPOSURE_MAX', 15.0) * 1000)
        context['refreshInterval'] = refreshInterval_ms

        return context


class ImageLoopView(TemplateView):
    def get_context(self):
        context = super(ImageLoopView, self).get_context()

        refreshInterval_ms = math.ceil(self.indi_allsky_config.get('CCD_EXPOSURE_MAX', 15.0) * 1000)
        context['refreshInterval'] = refreshInterval_ms

        context['form_history'] = IndiAllskyHistoryForm()

        return context


class JsonImageLoopView(JsonView):
    def __init__(self, **kwargs):
        super(JsonImageLoopView, self).__init__(**kwargs)

        self.history_seconds = 900
        self.sqm_history_minutes = 30
        self.stars_history_minutes = 30
        self.limit = 1000  # sanity check


    def get_objects(self):
        history_seconds = int(request.args.get('limit_s', self.history_seconds))
        self.limit = int(request.args.get('limit', self.limit))

        # sanity check
        if history_seconds > 86400:
            history_seconds = 86400

        data = {
            'image_list' : self.getLatestImages(session['camera_id'], history_seconds),
            'sqm_data'   : self.getSqmData(session['camera_id']),
            'stars_data' : self.getStarsData(session['camera_id']),
        }

        return data


    def getLatestImages(self, camera_id, history_seconds):
        now_minus_seconds = datetime.now() - timedelta(seconds=history_seconds)

        latest_images_q = IndiAllSkyDbImageTable.query\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == camera_id,
                    IndiAllSkyDbImageTable.createDate > now_minus_seconds,
                )
            )


        if self.indi_allsky_config.get('WEB_NONLOCAL_IMAGES'):
            # Do not serve local assets
            latest_images_q = latest_images_q\
                .filter(
                    or_(
                        IndiAllSkyDbImageTable.remote_url != sa_null(),
                        IndiAllSkyDbImageTable.s3_key != sa_null(),
                    )
                )


        latest_images = latest_images_q\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())\
            .limit(self.limit)


        image_list = list()
        for i in latest_images:
            try:
                url = i.getUrl(s3_prefix=self.s3_prefix)
            except ValueError as e:
                app.logger.error('Error determining relative file name: %s', str(e))
                continue

            data = {
                'url'        : str(url),
                'sqm'        : i.sqm,
                'stars'      : i.stars,
                'detections' : i.detections,
            }

            image_list.append(data)

        return image_list


    def getSqmData(self, camera_id):
        now_minus_minutes = datetime.now() - timedelta(minutes=self.sqm_history_minutes)

        sqm_images = IndiAllSkyDbImageTable.query\
            .add_columns(
                func.max(IndiAllSkyDbImageTable.sqm).label('image_max_sqm'),
                func.min(IndiAllSkyDbImageTable.sqm).label('image_min_sqm'),
                func.avg(IndiAllSkyDbImageTable.sqm).label('image_avg_sqm'),
            )\
            .join(IndiAllSkyDbCameraTable)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == camera_id,
                    IndiAllSkyDbImageTable.createDate > now_minus_minutes,
                )
            )\
            .first()


        sqm_data = {
            'max' : sqm_images.image_max_sqm,
            'min' : sqm_images.image_min_sqm,
            'avg' : sqm_images.image_avg_sqm,
        }

        return sqm_data


    def getStarsData(self, camera_id):
        now_minus_minutes = datetime.now() - timedelta(minutes=self.stars_history_minutes)

        stars_images = IndiAllSkyDbImageTable.query\
            .add_columns(
                func.max(IndiAllSkyDbImageTable.stars).label('image_max_stars'),
                func.min(IndiAllSkyDbImageTable.stars).label('image_min_stars'),
                func.avg(IndiAllSkyDbImageTable.stars).label('image_avg_stars'),
            )\
            .join(IndiAllSkyDbCameraTable)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == camera_id,
                    IndiAllSkyDbImageTable.createDate > now_minus_minutes,
                )
            )\
            .first()


        stars_data = {
            'max' : stars_images.image_max_stars,
            'min' : stars_images.image_min_stars,
            'avg' : stars_images.image_avg_stars,
        }

        return stars_data


class ChartView(TemplateView):
    def get_context(self):
        context = super(ChartView, self).get_context()

        refreshInterval_ms = math.ceil(self.indi_allsky_config.get('CCD_EXPOSURE_MAX', 15.0) * 1000)
        context['refreshInterval'] = refreshInterval_ms

        context['form_history'] = IndiAllskyHistoryForm()

        return context


class JsonChartView(JsonView):
    def __init__(self, **kwargs):
        super(JsonChartView, self).__init__(**kwargs)

        self.chart_history_seconds = 900


    def get_objects(self):
        history_seconds = int(request.args.get('limit_s', self.chart_history_seconds))

        # safety, limit history to 1 day
        if history_seconds > 86400:
            history_seconds = 86400


        data = {
            'chart_data' : self.getChartData(history_seconds),
        }

        return data


    def getChartData(self, history_seconds):
        now_minus_seconds = datetime.now() - timedelta(seconds=history_seconds)

        chart_query = IndiAllSkyDbImageTable.query\
            .add_columns(
                IndiAllSkyDbImageTable.createDate,
                IndiAllSkyDbImageTable.sqm,
                func.avg(IndiAllSkyDbImageTable.stars).over(order_by=IndiAllSkyDbImageTable.createDate, rows=(-5, 0)).label('stars_rolling'),
                IndiAllSkyDbImageTable.temp,
                IndiAllSkyDbImageTable.exposure,
                IndiAllSkyDbImageTable.detections,
                (IndiAllSkyDbImageTable.sqm - func.lag(IndiAllSkyDbImageTable.sqm).over(order_by=IndiAllSkyDbImageTable.createDate)).label('sqm_diff'),
            )\
            .join(IndiAllSkyDbCameraTable)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == session['camera_id'],
                    IndiAllSkyDbImageTable.createDate > now_minus_seconds,
                )
            )\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())


        #app.logger.info('Chart SQL: %s', str(chart_query))

        chart_data = {
            'sqm'   : [],
            'sqm_d' : [],
            'stars' : [],
            'temp'  : [],
            'exp'   : [],
            'detection': [],
            'histogram' : {
                'red'   : [],
                'green' : [],
                'blue'  : [],
                'gray'  : [],
            },
        }
        for i in chart_query:
            sqm_data = {
                'x' : i.createDate.strftime('%H:%M:%S'),
                'y' : i.sqm,
            }
            chart_data['sqm'].append(sqm_data)

            star_data = {
                'x' : i.createDate.strftime('%H:%M:%S'),
                'y' : int(i.stars_rolling),
            }
            chart_data['stars'].append(star_data)


            if self.indi_allsky_config.get('TEMP_DISPLAY') == 'f':
                sensortemp = ((i.temp * 9.0) / 5.0) + 32
            elif self.indi_allsky_config.get('TEMP_DISPLAY') == 'k':
                sensortemp = i.temp + 273.15
            else:
                sensortemp = i.temp

            temp_data = {
                'x' : i.createDate.strftime('%H:%M:%S'),
                'y' : sensortemp,
            }
            chart_data['temp'].append(temp_data)

            exp_data = {
                'x' : i.createDate.strftime('%H:%M:%S'),
                'y' : i.exposure,
            }
            chart_data['exp'].append(exp_data)

            sqm_d_data = {
                'x' : i.createDate.strftime('%H:%M:%S'),
                'y' : i.sqm_diff,
            }
            chart_data['sqm_d'].append(sqm_d_data)


            if i.detections > 0:
                detection = 1
            else:
                detection = 0

            detection_data = {
                'x' : i.createDate.strftime('%H:%M:%S'),
                'y' : detection,
            }
            chart_data['detection'].append(detection_data)



        # build last image histogram
        now_minus_seconds = datetime.now() - timedelta(seconds=history_seconds)

        latest_image = IndiAllSkyDbImageTable.query\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == session['camera_id'],
                    IndiAllSkyDbImageTable.createDate > now_minus_seconds,
                )
            )\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())\
            .first()


        if not latest_image:
            return chart_data


        latest_image_p = Path(latest_image.filename)
        if not latest_image_p.exists():
            app.logger.error('Image does not exist: %s', latest_image_p)
            return chart_data


        image_start = time.time()

        image_data = cv2.imread(str(latest_image_p), cv2.IMREAD_UNCHANGED)

        if isinstance(image_data, type(None)):
            app.logger.error('Unable to read %s', latest_image_p)
            return chart_data

        image_elapsed_s = time.time() - image_start
        app.logger.info('Image read in %0.4f s', image_elapsed_s)


        image_height, image_width = image_data.shape[:2]
        app.logger.info('Calculating histogram from RoI')

        mask = numpy.zeros(image_data.shape[:2], numpy.uint8)

        x1 = int((image_width / 2) - (image_width / 3))
        y1 = int((image_height / 2) - (image_height / 3))
        x2 = int((image_width / 2) + (image_width / 3))
        y2 = int((image_height / 2) + (image_height / 3))

        mask[y1:y2, x1:x2] = 255


        if len(image_data.shape) == 2:
            # mono
            h_numpy = cv2.calcHist([image_data], [0], mask, [256], [0, 256])
            for x, val in enumerate(h_numpy.tolist()):
                h_data = {
                    'x' : str(x),
                    'y' : val[0],
                }
                chart_data['histogram']['gray'].append(h_data)

        else:
            # color
            color = ('blue', 'green', 'red')
            for i, col in enumerate(color):
                h_numpy = cv2.calcHist([image_data], [i], mask, [256], [0, 256])
                for x, val in enumerate(h_numpy.tolist()):
                    h_data = {
                        'x' : str(x),
                        'y' : val[0],
                    }
                    chart_data['histogram'][col].append(h_data)


        return chart_data


class ConfigView(FormView):
    decorators = [login_required]

    def get_context(self):
        context = super(ConfigView, self).get_context()

        form_data = {
            'CAMERA_INTERFACE'               : self.indi_allsky_config.get('CAMERA_INTERFACE', 'indi'),
            'INDI_SERVER'                    : self.indi_allsky_config.get('INDI_SERVER', 'localhost'),
            'INDI_PORT'                      : self.indi_allsky_config.get('INDI_PORT', 7624),
            'INDI_CAMERA_NAME'               : self.indi_allsky_config.get('INDI_CAMERA_NAME', ''),
            'LENS_NAME'                      : self.indi_allsky_config.get('LENS_NAME', 'AllSky Lens'),
            'LENS_FOCAL_LENGTH'              : self.indi_allsky_config.get('LENS_FOCAL_LENGTH', 2.5),
            'LENS_FOCAL_RATIO'               : self.indi_allsky_config.get('LENS_FOCAL_RATIO', 2.0),
            'LENS_ALTITUDE'                  : self.indi_allsky_config.get('LENS_ALTITUDE', 90.0),
            'LENS_AZIMUTH'                   : self.indi_allsky_config.get('LENS_AZIMUTH', 0.0),
            'CCD_CONFIG__NIGHT__GAIN'        : self.indi_allsky_config.get('CCD_CONFIG', {}).get('NIGHT', {}).get('GAIN', 100),
            'CCD_CONFIG__NIGHT__BINNING'     : self.indi_allsky_config.get('CCD_CONFIG', {}).get('NIGHT', {}).get('BINNING', 1),
            'CCD_CONFIG__MOONMODE__GAIN'     : self.indi_allsky_config.get('CCD_CONFIG', {}).get('MOONMODE', {}).get('GAIN', 75),
            'CCD_CONFIG__MOONMODE__BINNING'  : self.indi_allsky_config.get('CCD_CONFIG', {}).get('MOONMODE', {}).get('BINNING', 1),
            'CCD_CONFIG__DAY__GAIN'          : self.indi_allsky_config.get('CCD_CONFIG', {}).get('DAY', {}).get('GAIN', 0),
            'CCD_CONFIG__DAY__BINNING'       : self.indi_allsky_config.get('CCD_CONFIG', {}).get('DAY', {}).get('BINNING', 1),
            'CCD_EXPOSURE_MAX'               : self.indi_allsky_config.get('CCD_EXPOSURE_MAX', 15.0),
            'CCD_EXPOSURE_DEF'               : self.indi_allsky_config.get('CCD_EXPOSURE_DEF', 0.0),
            'CCD_EXPOSURE_MIN'               : self.indi_allsky_config.get('CCD_EXPOSURE_MIN', 0.0),
            'EXPOSURE_PERIOD'                : self.indi_allsky_config.get('EXPOSURE_PERIOD', 15.0),
            'EXPOSURE_PERIOD_DAY'            : self.indi_allsky_config.get('EXPOSURE_PERIOD_DAY', 15.0),
            'FOCUS_MODE'                     : self.indi_allsky_config.get('FOCUS_MODE', False),
            'FOCUS_DELAY'                    : self.indi_allsky_config.get('FOCUS_DELAY', 4.0),
            'CFA_PATTERN'                    : self.indi_allsky_config.get('CFA_PATTERN', ''),
            'SCNR_ALGORITHM'                 : self.indi_allsky_config.get('SCNR_ALGORITHM', ''),
            'WBR_FACTOR'                     : self.indi_allsky_config.get('WBR_FACTOR', 1.0),
            'WBG_FACTOR'                     : self.indi_allsky_config.get('WBG_FACTOR', 1.0),
            'WBB_FACTOR'                     : self.indi_allsky_config.get('WBB_FACTOR', 1.0),
            'AUTO_WB'                        : self.indi_allsky_config.get('AUTO_WB', False),
            'CCD_COOLING'                    : self.indi_allsky_config.get('CCD_COOLING', False),
            'CCD_TEMP'                       : self.indi_allsky_config.get('CCD_TEMP', 15.0),
            'TEMP_DISPLAY'                   : self.indi_allsky_config.get('TEMP_DISPLAY', 'c'),
            'CCD_TEMP_SCRIPT'                : self.indi_allsky_config.get('CCD_TEMP_SCRIPT', ''),
            'GPS_TIMESYNC'                   : self.indi_allsky_config.get('GPS_TIMESYNC', False),
            'TARGET_ADU'                     : self.indi_allsky_config.get('TARGET_ADU', 75),
            'TARGET_ADU_DAY'                 : self.indi_allsky_config.get('TARGET_ADU_DAY', 75),
            'TARGET_ADU_DEV'                 : self.indi_allsky_config.get('TARGET_ADU_DEV', 10),
            'TARGET_ADU_DEV_DAY'             : self.indi_allsky_config.get('TARGET_ADU_DEV_DAY', 20),
            'DETECT_STARS'                   : self.indi_allsky_config.get('DETECT_STARS', True),
            'DETECT_STARS_THOLD'             : self.indi_allsky_config.get('DETECT_STARS_THOLD', 0.6),
            'DETECT_METEORS'                 : self.indi_allsky_config.get('DETECT_METEORS', False),
            'DETECT_MASK'                    : self.indi_allsky_config.get('DETECT_MASK', ''),
            'DETECT_DRAW'                    : self.indi_allsky_config.get('DETECT_DRAW', False),
            'LOGO_OVERLAY'                   : self.indi_allsky_config.get('LOGO_OVERLAY', ''),
            'LOCATION_NAME'                  : self.indi_allsky_config.get('LOCATION_NAME', ''),
            'LOCATION_LATITUDE'              : self.indi_allsky_config.get('LOCATION_LATITUDE', 0.0),
            'LOCATION_LONGITUDE'             : self.indi_allsky_config.get('LOCATION_LONGITUDE', 0.0),
            'TIMELAPSE_ENABLE'               : self.indi_allsky_config.get('TIMELAPSE_ENABLE', True),
            'DAYTIME_CAPTURE'                : self.indi_allsky_config.get('DAYTIME_CAPTURE', True),
            'DAYTIME_TIMELAPSE'              : self.indi_allsky_config.get('DAYTIME_TIMELAPSE', True),
            'DAYTIME_CONTRAST_ENHANCE'       : self.indi_allsky_config.get('DAYTIME_CONTRAST_ENHANCE', False),
            'NIGHT_CONTRAST_ENHANCE'         : self.indi_allsky_config.get('NIGHT_CONTRAST_ENHANCE', False),
            'NIGHT_SUN_ALT_DEG'              : self.indi_allsky_config.get('NIGHT_SUN_ALT_DEG', -6.0),
            'NIGHT_MOONMODE_ALT_DEG'         : self.indi_allsky_config.get('NIGHT_MOONMODE_ALT_DEG', 5.0),
            'NIGHT_MOONMODE_PHASE'           : self.indi_allsky_config.get('NIGHT_MOONMODE_PHASE', 50.0),
            'WEB_EXTRA_TEXT'                 : self.indi_allsky_config.get('WEB_EXTRA_TEXT', ''),
            'WEB_NONLOCAL_IMAGES'            : self.indi_allsky_config.get('WEB_NONLOCAL_IMAGES', False),
            'KEOGRAM_ANGLE'                  : self.indi_allsky_config.get('KEOGRAM_ANGLE', 0.0),
            'KEOGRAM_H_SCALE'                : self.indi_allsky_config.get('KEOGRAM_H_SCALE', 100),
            'KEOGRAM_V_SCALE'                : self.indi_allsky_config.get('KEOGRAM_V_SCALE', 33),
            'KEOGRAM_LABEL'                  : self.indi_allsky_config.get('KEOGRAM_LABEL', True),
            'STARTRAILS_MAX_ADU'             : self.indi_allsky_config.get('STARTRAILS_MAX_ADU', 50),
            'STARTRAILS_MASK_THOLD'          : self.indi_allsky_config.get('STARTRAILS_MASK_THOLD', 190),
            'STARTRAILS_PIXEL_THOLD'         : self.indi_allsky_config.get('STARTRAILS_PIXEL_THOLD', 0.1),
            'STARTRAILS_TIMELAPSE'           : self.indi_allsky_config.get('STARTRAILS_TIMELAPSE', True),
            'STARTRAILS_TIMELAPSE_MINFRAMES' : self.indi_allsky_config.get('STARTRAILS_TIMELAPSE_MINFRAMES', 250),
            'IMAGE_FILE_TYPE'                : self.indi_allsky_config.get('IMAGE_FILE_TYPE', 'jpg'),
            'IMAGE_FILE_COMPRESSION__JPG'    : self.indi_allsky_config.get('IMAGE_FILE_COMPRESSION', {}).get('jpg', 90),
            'IMAGE_FILE_COMPRESSION__PNG'    : self.indi_allsky_config.get('IMAGE_FILE_COMPRESSION', {}).get('png', 5),
            'IMAGE_FILE_COMPRESSION__TIF'    : self.indi_allsky_config.get('IMAGE_FILE_COMPRESSION', {}).get('tif', 5),
            'IMAGE_FOLDER'                   : self.indi_allsky_config.get('IMAGE_FOLDER', '/var/www/html/allsky/images'),
            'IMAGE_LABEL'                    : self.indi_allsky_config.get('IMAGE_LABEL', True),
            'IMAGE_LABEL_TEMPLATE'           : self.indi_allsky_config.get('IMAGE_LABEL_TEMPLATE', '{timestamp:%Y%m%d %H:%M:%S}\nExposure {exposure:0.6f}\nGain {gain:d}\nTemp {temp:0.1f}{temp_unit:s}\nStars {stars:d}'),
            'IMAGE_EXTRA_TEXT'               : self.indi_allsky_config.get('IMAGE_EXTRA_TEXT', ''),
            'IMAGE_ROTATE'                   : self.indi_allsky_config.get('IMAGE_ROTATE', ''),
            'IMAGE_FLIP_V'                   : self.indi_allsky_config.get('IMAGE_FLIP_V', True),
            'IMAGE_FLIP_H'                   : self.indi_allsky_config.get('IMAGE_FLIP_H', True),
            'IMAGE_SCALE'                    : self.indi_allsky_config.get('IMAGE_SCALE', 100),
            'IMAGE_CIRCLE_MASK__ENABLE'      : self.indi_allsky_config.get('IMAGE_CIRCLE_MASK', {}).get('ENABLE', False),
            'IMAGE_CIRCLE_MASK__DIAMETER'    : self.indi_allsky_config.get('IMAGE_CIRCLE_MASK', {}).get('DIAMETER', 1000),
            'IMAGE_CIRCLE_MASK__OFFSET_X'    : self.indi_allsky_config.get('IMAGE_CIRCLE_MASK', {}).get('OFFSET_X', 0),
            'IMAGE_CIRCLE_MASK__OFFSET_Y'    : self.indi_allsky_config.get('IMAGE_CIRCLE_MASK', {}).get('OFFSET_Y', 0),
            'IMAGE_CIRCLE_MASK__BLUR'        : self.indi_allsky_config.get('IMAGE_CIRCLE_MASK', {}).get('BLUR', 35),
            'IMAGE_CIRCLE_MASK__OPACITY'     : self.indi_allsky_config.get('IMAGE_CIRCLE_MASK', {}).get('OPACITY', 100),
            'IMAGE_CIRCLE_MASK__OUTLINE'     : self.indi_allsky_config.get('IMAGE_CIRCLE_MASK', {}).get('OUTLINE', False),
            'IMAGE_SAVE_FITS'                : self.indi_allsky_config.get('IMAGE_SAVE_FITS', False),
            'NIGHT_GRAYSCALE'                : self.indi_allsky_config.get('NIGHT_GRAYSCALE', False),
            'DAYTIME_GRAYSCALE'              : self.indi_allsky_config.get('DAYTIME_GRAYSCALE', False),
            'IMAGE_EXPORT_RAW'               : self.indi_allsky_config.get('IMAGE_EXPORT_RAW', ''),
            'IMAGE_EXPORT_FOLDER'            : self.indi_allsky_config.get('IMAGE_EXPORT_FOLDER', '/var/www/html/allsky/images/export'),
            'IMAGE_STACK_METHOD'             : self.indi_allsky_config.get('IMAGE_STACK_METHOD', 'maximum'),
            'IMAGE_STACK_COUNT'              : str(self.indi_allsky_config.get('IMAGE_STACK_COUNT', 1)),  # string in form, int in config
            'IMAGE_STACK_ALIGN'              : self.indi_allsky_config.get('IMAGE_STACK_ALIGN', False),
            'IMAGE_ALIGN_DETECTSIGMA'        : self.indi_allsky_config.get('IMAGE_ALIGN_DETECTSIGMA', 5),
            'IMAGE_ALIGN_POINTS'             : self.indi_allsky_config.get('IMAGE_ALIGN_POINTS', 50),
            'IMAGE_ALIGN_SOURCEMINAREA'      : self.indi_allsky_config.get('IMAGE_ALIGN_SOURCEMINAREA', 10),
            'IMAGE_STACK_SPLIT'              : self.indi_allsky_config.get('IMAGE_STACK_SPLIT', False),
            'IMAGE_EXPIRE_DAYS'              : self.indi_allsky_config.get('IMAGE_EXPIRE_DAYS', 30),
            'TIMELAPSE_EXPIRE_DAYS'          : self.indi_allsky_config.get('TIMELAPSE_EXPIRE_DAYS', 365),
            'FFMPEG_FRAMERATE'               : self.indi_allsky_config.get('FFMPEG_FRAMERATE', 25),
            'FFMPEG_BITRATE'                 : self.indi_allsky_config.get('FFMPEG_BITRATE', '2500k'),
            'FFMPEG_VFSCALE'                 : self.indi_allsky_config.get('FFMPEG_VFSCALE', ''),
            'FFMPEG_CODEC'                   : self.indi_allsky_config.get('FFMPEG_CODEC', 'libx264'),
            'TEXT_PROPERTIES__FONT_FACE'     : self.indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_FACE', 'FONT_HERSHEY_SIMPLEX'),
            'TEXT_PROPERTIES__FONT_HEIGHT'   : self.indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_HEIGHT', 30),
            'TEXT_PROPERTIES__FONT_X'        : self.indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_X', 15),
            'TEXT_PROPERTIES__FONT_Y'        : self.indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_Y', 30),
            'TEXT_PROPERTIES__FONT_SCALE'    : self.indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_SCALE', 0.8),
            'TEXT_PROPERTIES__FONT_THICKNESS': self.indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_THICKNESS', 1),
            'TEXT_PROPERTIES__FONT_OUTLINE'  : self.indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_OUTLINE', True),
            'TEXT_PROPERTIES__DATE_FORMAT'   : self.indi_allsky_config.get('TEXT_PROPERTIES', {}).get('DATE_FORMAT', '%Y%m%d %H:%M:%S'),
            'ORB_PROPERTIES__MODE'           : self.indi_allsky_config.get('ORB_PROPERTIES', {}).get('MODE', 'ha'),
            'ORB_PROPERTIES__RADIUS'         : self.indi_allsky_config.get('ORB_PROPERTIES', {}).get('RADIUS', 9),
            'UPLOAD_WORKERS'                 : self.indi_allsky_config.get('UPLOAD_WORKERS', 1),
            'FILETRANSFER__CLASSNAME'        : self.indi_allsky_config.get('FILETRANSFER', {}).get('CLASSNAME', 'pycurl_sftp'),
            'FILETRANSFER__HOST'             : self.indi_allsky_config.get('FILETRANSFER', {}).get('HOST', ''),
            'FILETRANSFER__PORT'             : self.indi_allsky_config.get('FILETRANSFER', {}).get('PORT', 0),
            'FILETRANSFER__USERNAME'         : self.indi_allsky_config.get('FILETRANSFER', {}).get('USERNAME', ''),
            'FILETRANSFER__PASSWORD'         : self.indi_allsky_config.get('FILETRANSFER', {}).get('PASSWORD', ''),
            'FILETRANSFER__PRIVATE_KEY'      : self.indi_allsky_config.get('FILETRANSFER', {}).get('PRIVATE_KEY', ''),
            'FILETRANSFER__PUBLIC_KEY'       : self.indi_allsky_config.get('FILETRANSFER', {}).get('PUBLIC_KEY', ''),
            'FILETRANSFER__TIMEOUT'          : self.indi_allsky_config.get('FILETRANSFER', {}).get('TIMEOUT', 5.0),
            'FILETRANSFER__CERT_BYPASS'      : self.indi_allsky_config.get('FILETRANSFER', {}).get('CERT_BYPASS', True),
            'FILETRANSFER__REMOTE_IMAGE_NAME'         : self.indi_allsky_config.get('FILETRANSFER', {}).get('REMOTE_IMAGE_NAME', 'image.{0}'),
            'FILETRANSFER__REMOTE_IMAGE_FOLDER'       : self.indi_allsky_config.get('FILETRANSFER', {}).get('REMOTE_IMAGE_FOLDER', 'allsky'),
            'FILETRANSFER__REMOTE_METADATA_NAME'      : self.indi_allsky_config.get('FILETRANSFER', {}).get('REMOTE_METADATA_NAME', 'latest_metadata.json'),
            'FILETRANSFER__REMOTE_METADATA_FOLDER'    : self.indi_allsky_config.get('FILETRANSFER', {}).get('REMOTE_METADATA_FOLDER', 'allsky'),
            'FILETRANSFER__REMOTE_VIDEO_FOLDER'       : self.indi_allsky_config.get('FILETRANSFER', {}).get('REMOTE_VIDEO_FOLDER', 'allsky/videos'),
            'FILETRANSFER__REMOTE_KEOGRAM_FOLDER'     : self.indi_allsky_config.get('FILETRANSFER', {}).get('REMOTE_KEOGRAM_FOLDER', 'allsky/keograms'),
            'FILETRANSFER__REMOTE_STARTRAIL_FOLDER'   : self.indi_allsky_config.get('FILETRANSFER', {}).get('REMOTE_STARTRAIL_FOLDER', 'allsky/startrails'),
            'FILETRANSFER__REMOTE_ENDOFNIGHT_FOLDER'  : self.indi_allsky_config.get('FILETRANSFER', {}).get('REMOTE_ENDOFNIGHT_FOLDER', 'allsky'),
            'FILETRANSFER__UPLOAD_IMAGE'     : self.indi_allsky_config.get('FILETRANSFER', {}).get('UPLOAD_IMAGE', 0),
            'FILETRANSFER__UPLOAD_METADATA'  : self.indi_allsky_config.get('FILETRANSFER', {}).get('UPLOAD_METADATA', False),
            'FILETRANSFER__UPLOAD_VIDEO'     : self.indi_allsky_config.get('FILETRANSFER', {}).get('UPLOAD_VIDEO', False),
            'FILETRANSFER__UPLOAD_KEOGRAM'   : self.indi_allsky_config.get('FILETRANSFER', {}).get('UPLOAD_KEOGRAM', False),
            'FILETRANSFER__UPLOAD_STARTRAIL' : self.indi_allsky_config.get('FILETRANSFER', {}).get('UPLOAD_STARTRAIL', False),
            'FILETRANSFER__UPLOAD_ENDOFNIGHT': self.indi_allsky_config.get('FILETRANSFER', {}).get('UPLOAD_ENDOFNIGHT', False),
            'S3UPLOAD__CLASSNAME'            : self.indi_allsky_config.get('S3UPLOAD', {}).get('CLASSNAME', 'boto3_s3'),
            'S3UPLOAD__ENABLE'               : self.indi_allsky_config.get('S3UPLOAD', {}).get('ENABLE', False),
            'S3UPLOAD__ACCESS_KEY'           : self.indi_allsky_config.get('S3UPLOAD', {}).get('ACCESS_KEY', ''),
            'S3UPLOAD__SECRET_KEY'           : self.indi_allsky_config.get('S3UPLOAD', {}).get('SECRET_KEY', ''),
            'S3UPLOAD__BUCKET'               : self.indi_allsky_config.get('S3UPLOAD', {}).get('BUCKET', 'change-me'),
            'S3UPLOAD__REGION'               : self.indi_allsky_config.get('S3UPLOAD', {}).get('REGION', 'us-east-2'),
            'S3UPLOAD__HOST'                 : self.indi_allsky_config.get('S3UPLOAD', {}).get('HOST', 'amazonaws.com'),
            'S3UPLOAD__PORT'                 : self.indi_allsky_config.get('S3UPLOAD', {}).get('PORT', 0),
            'S3UPLOAD__URL_TEMPLATE'         : self.indi_allsky_config.get('S3UPLOAD', {}).get('URL_TEMPLATE', 'https://{bucket}.s3.{region}.{host}'),
            'S3UPLOAD__STORAGE_CLASS'        : self.indi_allsky_config.get('S3UPLOAD', {}).get('STORAGE_CLASS', 'STANDARD'),
            'S3UPLOAD__ACL'                  : self.indi_allsky_config.get('S3UPLOAD', {}).get('ACL', 'public-read'),
            'S3UPLOAD__EXPIRE_IMAGES'        : self.indi_allsky_config.get('S3UPLOAD', {}).get('EXPIRE_IMAGES', True),
            'S3UPLOAD__EXPIRE_TIMELAPSE'     : self.indi_allsky_config.get('S3UPLOAD', {}).get('EXPIRE_TIMELAPSE', True),
            'S3UPLOAD__TLS'                  : self.indi_allsky_config.get('S3UPLOAD', {}).get('TLS', True),
            'S3UPLOAD__CERT_BYPASS'          : self.indi_allsky_config.get('S3UPLOAD', {}).get('CERT_BYPASS', False),
            'MQTTPUBLISH__ENABLE'            : self.indi_allsky_config.get('MQTTPUBLISH', {}).get('ENABLE', False),
            'MQTTPUBLISH__TRANSPORT'         : self.indi_allsky_config.get('MQTTPUBLISH', {}).get('TRANSPORT', 'tcp'),
            'MQTTPUBLISH__HOST'              : self.indi_allsky_config.get('MQTTPUBLISH', {}).get('HOST', 'localhost'),
            'MQTTPUBLISH__PORT'              : self.indi_allsky_config.get('MQTTPUBLISH', {}).get('PORT', 8883),
            'MQTTPUBLISH__USERNAME'          : self.indi_allsky_config.get('MQTTPUBLISH', {}).get('USERNAME', 'indi-allsky'),
            'MQTTPUBLISH__PASSWORD'          : self.indi_allsky_config.get('MQTTPUBLISH', {}).get('PASSWORD', ''),
            'MQTTPUBLISH__BASE_TOPIC'        : self.indi_allsky_config.get('MQTTPUBLISH', {}).get('BASE_TOPIC', 'indi-allsky'),
            'MQTTPUBLISH__QOS'               : self.indi_allsky_config.get('MQTTPUBLISH', {}).get('QOS', 0),
            'MQTTPUBLISH__TLS'               : self.indi_allsky_config.get('MQTTPUBLISH', {}).get('TLS', True),
            'MQTTPUBLISH__CERT_BYPASS'       : self.indi_allsky_config.get('MQTTPUBLISH', {}).get('CERT_BYPASS', True),
            'SYNCAPI__ENABLE'                : self.indi_allsky_config.get('SYNCAPI', {}).get('ENABLE', False),
            'SYNCAPI__BASEURL'               : self.indi_allsky_config.get('SYNCAPI', {}).get('BASEURL', 'https://example.com/indi-allsky'),
            'SYNCAPI__USERNAME'              : self.indi_allsky_config.get('SYNCAPI', {}).get('USERNAME', ''),
            'SYNCAPI__APIKEY'                : self.indi_allsky_config.get('SYNCAPI', {}).get('APIKEY', ''),
            'SYNCAPI__CERT_BYPASS'           : self.indi_allsky_config.get('SYNCAPI', {}).get('CERT_BYPASS', False),
            'SYNCAPI__POST_S3'               : self.indi_allsky_config.get('SYNCAPI', {}).get('POST_S3', False),
            'LIBCAMERA__IMAGE_FILE_TYPE'     : self.indi_allsky_config.get('LIBCAMERA', {}).get('IMAGE_FILE_TYPE', 'dng'),
            'LIBCAMERA__EXTRA_OPTIONS'       : self.indi_allsky_config.get('LIBCAMERA', {}).get('EXTRA_OPTIONS', ''),
            'RELOAD_ON_SAVE'                 : False,
            'CONFIG_NOTE'                    : '',
            'ENCRYPT_PASSWORDS'              : self.indi_allsky_config.get('ENCRYPT_PASSWORDS', False),  # do not adjust
        }


        # ADU_ROI
        ADU_ROI = self.indi_allsky_config.get('ADU_ROI', [])
        if ADU_ROI is None:
            ADU_ROI = []
        elif isinstance(ADU_ROI, bool):
            ADU_ROI = []

        try:
            form_data['ADU_ROI_X1'] = ADU_ROI[0]
        except IndexError:
            form_data['ADU_ROI_X1'] = 0

        try:
            form_data['ADU_ROI_Y1'] = ADU_ROI[1]
        except IndexError:
            form_data['ADU_ROI_Y1'] = 0

        try:
            form_data['ADU_ROI_X2'] = ADU_ROI[2]
        except IndexError:
            form_data['ADU_ROI_X2'] = 0

        try:
            form_data['ADU_ROI_Y2'] = ADU_ROI[3]
        except IndexError:
            form_data['ADU_ROI_Y2'] = 0


        # SQM_ROI
        SQM_ROI = self.indi_allsky_config.get('SQM_ROI', [])
        if SQM_ROI is None:
            SQM_ROI = []
        elif isinstance(SQM_ROI, bool):
            SQM_ROI = []

        try:
            form_data['SQM_ROI_X1'] = SQM_ROI[0]
        except IndexError:
            form_data['SQM_ROI_X1'] = 0

        try:
            form_data['SQM_ROI_Y1'] = SQM_ROI[1]
        except IndexError:
            form_data['SQM_ROI_Y1'] = 0

        try:
            form_data['SQM_ROI_X2'] = SQM_ROI[2]
        except IndexError:
            form_data['SQM_ROI_X2'] = 0

        try:
            form_data['SQM_ROI_Y2'] = SQM_ROI[3]
        except IndexError:
            form_data['SQM_ROI_Y2'] = 0


        # IMAGE_CROP_ROI
        IMAGE_CROP_ROI = self.indi_allsky_config.get('IMAGE_CROP_ROI', [])
        if IMAGE_CROP_ROI is None:
            IMAGE_CROP_ROI = []
        elif isinstance(IMAGE_CROP_ROI, bool):
            IMAGE_CROP_ROI = []

        try:
            form_data['IMAGE_CROP_ROI_X1'] = IMAGE_CROP_ROI[0]
        except IndexError:
            form_data['IMAGE_CROP_ROI_X1'] = 0

        try:
            form_data['IMAGE_CROP_ROI_Y1'] = IMAGE_CROP_ROI[1]
        except IndexError:
            form_data['IMAGE_CROP_ROI_Y1'] = 0

        try:
            form_data['IMAGE_CROP_ROI_X2'] = IMAGE_CROP_ROI[2]
        except IndexError:
            form_data['IMAGE_CROP_ROI_X2'] = 0

        try:
            form_data['IMAGE_CROP_ROI_Y2'] = IMAGE_CROP_ROI[3]
        except IndexError:
            form_data['IMAGE_CROP_ROI_Y2'] = 0



        # Font color
        text_properties__font_color = self.indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_COLOR', [200, 200, 200])
        text_properties__font_color_str = [str(x) for x in text_properties__font_color]
        form_data['TEXT_PROPERTIES__FONT_COLOR'] = ','.join(text_properties__font_color_str)

        # Sun orb color
        orb_properties__sun_color = self.indi_allsky_config.get('ORB_PROPERTIES', {}).get('SUN_COLOR', [255, 255, 255])
        orb_properties__sun_color_str = [str(x) for x in orb_properties__sun_color]
        form_data['ORB_PROPERTIES__SUN_COLOR'] = ','.join(orb_properties__sun_color_str)

        # Moon orb color
        orb_properties__moon_color = self.indi_allsky_config.get('ORB_PROPERTIES', {}).get('MOON_COLOR', [128, 128, 128])
        orb_properties__moon_color_str = [str(x) for x in orb_properties__moon_color]
        form_data['ORB_PROPERTIES__MOON_COLOR'] = ','.join(orb_properties__moon_color_str)


        # FITS headers
        fitsheaders = self.indi_allsky_config.get('FITSHEADERS', [])

        try:
            form_data['FITSHEADERS__0__KEY'] = str(fitsheaders[0][0]).upper()
            form_data['FITSHEADERS__0__VAL'] = str(fitsheaders[0][1])
        except IndexError:
            form_data['FITSHEADERS__0__KEY'] = 'INSTRUME'
            form_data['FITSHEADERS__0__VAL'] = 'indi-allsky'

        try:
            form_data['FITSHEADERS__1__KEY'] = str(fitsheaders[1][0]).upper()
            form_data['FITSHEADERS__1__VAL'] = str(fitsheaders[1][1])
        except IndexError:
            form_data['FITSHEADERS__1__KEY'] = 'OBSERVER'
            form_data['FITSHEADERS__1__VAL'] = ''

        try:
            form_data['FITSHEADERS__2__KEY'] = str(fitsheaders[2][0]).upper()
            form_data['FITSHEADERS__2__VAL'] = str(fitsheaders[2][1])
        except IndexError:
            form_data['FITSHEADERS__2__KEY'] = 'SITE'
            form_data['FITSHEADERS__2__VAL'] = ''

        try:
            form_data['FITSHEADERS__3__KEY'] = str(fitsheaders[3][0]).upper()
            form_data['FITSHEADERS__3__VAL'] = str(fitsheaders[3][1])
        except IndexError:
            form_data['FITSHEADERS__3__KEY'] = 'OBJECT'
            form_data['FITSHEADERS__3__VAL'] = ''

        try:
            form_data['FITSHEADERS__4__KEY'] = str(fitsheaders[4][0]).upper()
            form_data['FITSHEADERS__4__VAL'] = str(fitsheaders[4][1])
        except IndexError:
            form_data['FITSHEADERS__4__KEY'] = 'NOTES'
            form_data['FITSHEADERS__4__VAL'] = ''


        # libcurl options as json text
        filetransfer__libcurl_options = self.indi_allsky_config.get('FILETRANSFER', {}).get('LIBCURL_OPTIONS', {})
        form_data['FILETRANSFER__LIBCURL_OPTIONS'] = json.dumps(filetransfer__libcurl_options, indent=4)

        # INDI config as json text
        indi_config_defaults = self.indi_allsky_config.get('INDI_CONFIG_DEFAULTS', {})
        form_data['INDI_CONFIG_DEFAULTS'] = json.dumps(indi_config_defaults, indent=4)


        # populated from flask config
        form_data['ADMIN_NETWORKS_FLASK'] = '\n'.join(app.config.get('ADMIN_NETWORKS', []))


        context['form_config'] = IndiAllskyConfigForm(data=form_data)

        return context


class AjaxConfigView(BaseView):
    methods = ['POST']
    decorators = [login_required]

    def dispatch_request(self):
        form_config = IndiAllskyConfigForm(data=request.json)


        if not app.config['LOGIN_DISABLED']:
            if not current_user.is_admin:
                form_errors = form_config.errors  # this must be a property
                form_errors['form_global'] = ['You do not have permission to make configuration changes']
                return jsonify(form_errors), 400


        if not form_config.validate():
            form_errors = form_config.errors  # this must be a property
            form_errors['form_global'] = ['Please fix the errors above']
            return jsonify(form_errors), 400


        # form passed validation

        if not self.indi_allsky_config:
            return jsonify({}), 400


        # sanity check
        if not self.indi_allsky_config.get('CCD_CONFIG'):
            self.indi_allsky_config['CCD_CONFIG'] = {}

        if not self.indi_allsky_config['CCD_CONFIG'].get('NIGHT'):
            self.indi_allsky_config['CCD_CONFIG']['NIGHT'] = {}

        if not self.indi_allsky_config['CCD_CONFIG'].get('MOONMODE'):
            self.indi_allsky_config['CCD_CONFIG']['MOONMODE'] = {}

        if not self.indi_allsky_config['CCD_CONFIG'].get('DAY'):
            self.indi_allsky_config['CCD_CONFIG']['DAY'] = {}

        if not self.indi_allsky_config.get('IMAGE_FILE_COMPRESSION'):
            self.indi_allsky_config['IMAGE_FILE_COMPRESSION'] = {}

        if not self.indi_allsky_config.get('IMAGE_CIRCLE_MASK'):
            self.indi_allsky_config['IMAGE_CIRCLE_MASK'] = {}

        if not self.indi_allsky_config.get('TEXT_PROPERTIES'):
            self.indi_allsky_config['TEXT_PROPERTIES'] = {}

        if not self.indi_allsky_config.get('ORB_PROPERTIES'):
            self.indi_allsky_config['ORB_PROPERTIES'] = {}

        if not self.indi_allsky_config.get('FILETRANSFER'):
            self.indi_allsky_config['FILETRANSFER'] = {}

        if not self.indi_allsky_config.get('S3UPLOAD'):
            self.indi_allsky_config['S3UPLOAD'] = {}

        if not self.indi_allsky_config.get('MQTTPUBLISH'):
            self.indi_allsky_config['MQTTPUBLISH'] = {}

        if not self.indi_allsky_config.get('SYNCAPI'):
            self.indi_allsky_config['SYNCAPI'] = {}

        if not self.indi_allsky_config.get('LIBCAMERA'):
            self.indi_allsky_config['LIBCAMERA'] = {}

        if not self.indi_allsky_config.get('FITSHEADERS'):
            self.indi_allsky_config['FITSHEADERS'] = [['', ''], ['', ''], ['', ''], ['', ''], ['', '']]

        # update data
        self.indi_allsky_config['CAMERA_INTERFACE']                     = str(request.json['CAMERA_INTERFACE'])
        self.indi_allsky_config['INDI_SERVER']                          = str(request.json['INDI_SERVER'])
        self.indi_allsky_config['INDI_PORT']                            = int(request.json['INDI_PORT'])
        self.indi_allsky_config['INDI_CAMERA_NAME']                     = str(request.json['INDI_CAMERA_NAME'])
        self.indi_allsky_config['LENS_NAME']                            = str(request.json['LENS_NAME'])
        self.indi_allsky_config['LENS_FOCAL_LENGTH']                    = float(request.json['LENS_FOCAL_LENGTH'])
        self.indi_allsky_config['LENS_FOCAL_RATIO']                     = float(request.json['LENS_FOCAL_RATIO'])
        self.indi_allsky_config['LENS_ALTITUDE']                        = float(request.json['LENS_ALTITUDE'])
        self.indi_allsky_config['LENS_AZIMUTH']                         = float(request.json['LENS_AZIMUTH'])
        self.indi_allsky_config['CCD_CONFIG']['NIGHT']['GAIN']          = int(request.json['CCD_CONFIG__NIGHT__GAIN'])
        self.indi_allsky_config['CCD_CONFIG']['NIGHT']['BINNING']       = int(request.json['CCD_CONFIG__NIGHT__BINNING'])
        self.indi_allsky_config['CCD_CONFIG']['MOONMODE']['GAIN']       = int(request.json['CCD_CONFIG__MOONMODE__GAIN'])
        self.indi_allsky_config['CCD_CONFIG']['MOONMODE']['BINNING']    = int(request.json['CCD_CONFIG__MOONMODE__BINNING'])
        self.indi_allsky_config['CCD_CONFIG']['DAY']['GAIN']            = int(request.json['CCD_CONFIG__DAY__GAIN'])
        self.indi_allsky_config['CCD_CONFIG']['DAY']['BINNING']         = int(request.json['CCD_CONFIG__DAY__BINNING'])
        self.indi_allsky_config['CCD_EXPOSURE_MAX']                     = float(request.json['CCD_EXPOSURE_MAX'])
        self.indi_allsky_config['CCD_EXPOSURE_DEF']                     = float(request.json['CCD_EXPOSURE_DEF'])
        self.indi_allsky_config['CCD_EXPOSURE_MIN']                     = float(request.json['CCD_EXPOSURE_MIN'])
        self.indi_allsky_config['EXPOSURE_PERIOD']                      = float(request.json['EXPOSURE_PERIOD'])
        self.indi_allsky_config['EXPOSURE_PERIOD_DAY']                  = float(request.json['EXPOSURE_PERIOD_DAY'])
        self.indi_allsky_config['FOCUS_MODE']                           = bool(request.json['FOCUS_MODE'])
        self.indi_allsky_config['FOCUS_DELAY']                          = float(request.json['FOCUS_DELAY'])
        self.indi_allsky_config['CFA_PATTERN']                          = str(request.json['CFA_PATTERN'])
        self.indi_allsky_config['SCNR_ALGORITHM']                       = str(request.json['SCNR_ALGORITHM'])
        self.indi_allsky_config['WBR_FACTOR']                           = float(request.json['WBR_FACTOR'])
        self.indi_allsky_config['WBG_FACTOR']                           = float(request.json['WBG_FACTOR'])
        self.indi_allsky_config['WBB_FACTOR']                           = float(request.json['WBB_FACTOR'])
        self.indi_allsky_config['CCD_COOLING']                          = bool(request.json['CCD_COOLING'])
        self.indi_allsky_config['CCD_TEMP']                             = float(request.json['CCD_TEMP'])
        self.indi_allsky_config['AUTO_WB']                              = bool(request.json['AUTO_WB'])
        self.indi_allsky_config['TEMP_DISPLAY']                         = str(request.json['TEMP_DISPLAY'])
        self.indi_allsky_config['GPS_TIMESYNC']                         = bool(request.json['GPS_TIMESYNC'])
        self.indi_allsky_config['CCD_TEMP_SCRIPT']                      = str(request.json['CCD_TEMP_SCRIPT'])
        self.indi_allsky_config['TARGET_ADU']                           = int(request.json['TARGET_ADU'])
        self.indi_allsky_config['TARGET_ADU_DAY']                       = int(request.json['TARGET_ADU_DAY'])
        self.indi_allsky_config['TARGET_ADU_DEV']                       = int(request.json['TARGET_ADU_DEV'])
        self.indi_allsky_config['TARGET_ADU_DEV_DAY']                   = int(request.json['TARGET_ADU_DEV_DAY'])
        self.indi_allsky_config['DETECT_STARS']                         = bool(request.json['DETECT_STARS'])
        self.indi_allsky_config['DETECT_STARS_THOLD']                   = float(request.json['DETECT_STARS_THOLD'])
        self.indi_allsky_config['DETECT_METEORS']                       = bool(request.json['DETECT_METEORS'])
        self.indi_allsky_config['DETECT_MASK']                          = str(request.json['DETECT_MASK'])
        self.indi_allsky_config['DETECT_DRAW']                          = bool(request.json['DETECT_DRAW'])
        self.indi_allsky_config['LOGO_OVERLAY']                         = str(request.json['LOGO_OVERLAY'])
        self.indi_allsky_config['LOCATION_NAME']                        = str(request.json['LOCATION_NAME'])
        self.indi_allsky_config['LOCATION_LATITUDE']                    = float(request.json['LOCATION_LATITUDE'])
        self.indi_allsky_config['LOCATION_LONGITUDE']                   = float(request.json['LOCATION_LONGITUDE'])
        self.indi_allsky_config['TIMELAPSE_ENABLE']                     = bool(request.json['TIMELAPSE_ENABLE'])
        self.indi_allsky_config['DAYTIME_CAPTURE']                      = bool(request.json['DAYTIME_CAPTURE'])
        self.indi_allsky_config['DAYTIME_TIMELAPSE']                    = bool(request.json['DAYTIME_TIMELAPSE'])
        self.indi_allsky_config['DAYTIME_CONTRAST_ENHANCE']             = bool(request.json['DAYTIME_CONTRAST_ENHANCE'])
        self.indi_allsky_config['NIGHT_CONTRAST_ENHANCE']               = bool(request.json['NIGHT_CONTRAST_ENHANCE'])
        self.indi_allsky_config['NIGHT_SUN_ALT_DEG']                    = float(request.json['NIGHT_SUN_ALT_DEG'])
        self.indi_allsky_config['NIGHT_MOONMODE_ALT_DEG']               = float(request.json['NIGHT_MOONMODE_ALT_DEG'])
        self.indi_allsky_config['NIGHT_MOONMODE_PHASE']                 = float(request.json['NIGHT_MOONMODE_PHASE'])
        self.indi_allsky_config['WEB_EXTRA_TEXT']                       = str(request.json['WEB_EXTRA_TEXT'])
        self.indi_allsky_config['WEB_NONLOCAL_IMAGES']                  = bool(request.json['WEB_NONLOCAL_IMAGES'])
        self.indi_allsky_config['KEOGRAM_ANGLE']                        = float(request.json['KEOGRAM_ANGLE'])
        self.indi_allsky_config['KEOGRAM_H_SCALE']                      = int(request.json['KEOGRAM_H_SCALE'])
        self.indi_allsky_config['KEOGRAM_V_SCALE']                      = int(request.json['KEOGRAM_V_SCALE'])
        self.indi_allsky_config['KEOGRAM_LABEL']                        = bool(request.json['KEOGRAM_LABEL'])
        self.indi_allsky_config['STARTRAILS_MAX_ADU']                   = int(request.json['STARTRAILS_MAX_ADU'])
        self.indi_allsky_config['STARTRAILS_MASK_THOLD']                = int(request.json['STARTRAILS_MASK_THOLD'])
        self.indi_allsky_config['STARTRAILS_PIXEL_THOLD']               = float(request.json['STARTRAILS_PIXEL_THOLD'])
        self.indi_allsky_config['STARTRAILS_TIMELAPSE']                 = bool(request.json['STARTRAILS_TIMELAPSE'])
        self.indi_allsky_config['STARTRAILS_TIMELAPSE_MINFRAMES']       = int(request.json['STARTRAILS_TIMELAPSE_MINFRAMES'])
        self.indi_allsky_config['IMAGE_FILE_TYPE']                      = str(request.json['IMAGE_FILE_TYPE'])
        self.indi_allsky_config['IMAGE_FILE_COMPRESSION']['jpg']        = int(request.json['IMAGE_FILE_COMPRESSION__JPG'])
        self.indi_allsky_config['IMAGE_FILE_COMPRESSION']['jpeg']       = int(request.json['IMAGE_FILE_COMPRESSION__JPG'])  # duplicate
        self.indi_allsky_config['IMAGE_FILE_COMPRESSION']['png']        = int(request.json['IMAGE_FILE_COMPRESSION__PNG'])
        self.indi_allsky_config['IMAGE_FILE_COMPRESSION']['tif']        = int(request.json['IMAGE_FILE_COMPRESSION__TIF'])
        self.indi_allsky_config['IMAGE_FILE_COMPRESSION']['tiff']       = int(request.json['IMAGE_FILE_COMPRESSION__TIF'])  # duplicate
        self.indi_allsky_config['IMAGE_FOLDER']                         = str(request.json['IMAGE_FOLDER'])
        self.indi_allsky_config['IMAGE_LABEL']                          = bool(request.json['IMAGE_LABEL'])
        self.indi_allsky_config['IMAGE_LABEL_TEMPLATE']                 = str(request.json['IMAGE_LABEL_TEMPLATE'])
        self.indi_allsky_config['IMAGE_EXTRA_TEXT']                     = str(request.json['IMAGE_EXTRA_TEXT'])
        self.indi_allsky_config['IMAGE_ROTATE']                         = str(request.json['IMAGE_ROTATE'])
        self.indi_allsky_config['IMAGE_FLIP_V']                         = bool(request.json['IMAGE_FLIP_V'])
        self.indi_allsky_config['IMAGE_FLIP_H']                         = bool(request.json['IMAGE_FLIP_H'])
        self.indi_allsky_config['IMAGE_SCALE']                          = int(request.json['IMAGE_SCALE'])
        self.indi_allsky_config['IMAGE_CIRCLE_MASK']['ENABLE']          = bool(request.json['IMAGE_CIRCLE_MASK__ENABLE'])
        self.indi_allsky_config['IMAGE_CIRCLE_MASK']['DIAMETER']        = int(request.json['IMAGE_CIRCLE_MASK__DIAMETER'])
        self.indi_allsky_config['IMAGE_CIRCLE_MASK']['OFFSET_X']        = int(request.json['IMAGE_CIRCLE_MASK__OFFSET_X'])
        self.indi_allsky_config['IMAGE_CIRCLE_MASK']['OFFSET_Y']        = int(request.json['IMAGE_CIRCLE_MASK__OFFSET_Y'])
        self.indi_allsky_config['IMAGE_CIRCLE_MASK']['BLUR']            = int(request.json['IMAGE_CIRCLE_MASK__BLUR'])
        self.indi_allsky_config['IMAGE_CIRCLE_MASK']['OPACITY']         = int(request.json['IMAGE_CIRCLE_MASK__OPACITY'])
        self.indi_allsky_config['IMAGE_CIRCLE_MASK']['OUTLINE']         = bool(request.json['IMAGE_CIRCLE_MASK__OUTLINE'])
        self.indi_allsky_config['IMAGE_SAVE_FITS']                      = bool(request.json['IMAGE_SAVE_FITS'])
        self.indi_allsky_config['NIGHT_GRAYSCALE']                      = bool(request.json['NIGHT_GRAYSCALE'])
        self.indi_allsky_config['DAYTIME_GRAYSCALE']                    = bool(request.json['DAYTIME_GRAYSCALE'])
        self.indi_allsky_config['IMAGE_EXPORT_RAW']                     = str(request.json['IMAGE_EXPORT_RAW'])
        self.indi_allsky_config['IMAGE_EXPORT_FOLDER']                  = str(request.json['IMAGE_EXPORT_FOLDER'])
        self.indi_allsky_config['IMAGE_STACK_METHOD']                   = str(request.json['IMAGE_STACK_METHOD'])
        self.indi_allsky_config['IMAGE_STACK_COUNT']                    = int(request.json['IMAGE_STACK_COUNT'])
        self.indi_allsky_config['IMAGE_STACK_ALIGN']                    = bool(request.json['IMAGE_STACK_ALIGN'])
        self.indi_allsky_config['IMAGE_ALIGN_DETECTSIGMA']              = int(request.json['IMAGE_ALIGN_DETECTSIGMA'])
        self.indi_allsky_config['IMAGE_ALIGN_POINTS']                   = int(request.json['IMAGE_ALIGN_POINTS'])
        self.indi_allsky_config['IMAGE_ALIGN_SOURCEMINAREA']            = int(request.json['IMAGE_ALIGN_SOURCEMINAREA'])
        self.indi_allsky_config['IMAGE_STACK_SPLIT']                    = bool(request.json['IMAGE_STACK_SPLIT'])
        self.indi_allsky_config['IMAGE_EXPIRE_DAYS']                    = int(request.json['IMAGE_EXPIRE_DAYS'])
        self.indi_allsky_config['TIMELAPSE_EXPIRE_DAYS']                = int(request.json['TIMELAPSE_EXPIRE_DAYS'])
        self.indi_allsky_config['FFMPEG_FRAMERATE']                     = int(request.json['FFMPEG_FRAMERATE'])
        self.indi_allsky_config['FFMPEG_BITRATE']                       = str(request.json['FFMPEG_BITRATE'])
        self.indi_allsky_config['FFMPEG_VFSCALE']                       = str(request.json['FFMPEG_VFSCALE'])
        self.indi_allsky_config['FFMPEG_CODEC']                         = str(request.json['FFMPEG_CODEC'])
        self.indi_allsky_config['TEXT_PROPERTIES']['FONT_FACE']         = str(request.json['TEXT_PROPERTIES__FONT_FACE'])
        self.indi_allsky_config['TEXT_PROPERTIES']['FONT_HEIGHT']       = int(request.json['TEXT_PROPERTIES__FONT_HEIGHT'])
        self.indi_allsky_config['TEXT_PROPERTIES']['FONT_X']            = int(request.json['TEXT_PROPERTIES__FONT_X'])
        self.indi_allsky_config['TEXT_PROPERTIES']['FONT_Y']            = int(request.json['TEXT_PROPERTIES__FONT_Y'])
        self.indi_allsky_config['TEXT_PROPERTIES']['FONT_SCALE']        = float(request.json['TEXT_PROPERTIES__FONT_SCALE'])
        self.indi_allsky_config['TEXT_PROPERTIES']['FONT_THICKNESS']    = int(request.json['TEXT_PROPERTIES__FONT_THICKNESS'])
        self.indi_allsky_config['TEXT_PROPERTIES']['FONT_OUTLINE']      = bool(request.json['TEXT_PROPERTIES__FONT_OUTLINE'])
        self.indi_allsky_config['TEXT_PROPERTIES']['DATE_FORMAT']       = str(request.json['TEXT_PROPERTIES__DATE_FORMAT'])
        self.indi_allsky_config['ORB_PROPERTIES']['MODE']               = str(request.json['ORB_PROPERTIES__MODE'])
        self.indi_allsky_config['ORB_PROPERTIES']['RADIUS']             = int(request.json['ORB_PROPERTIES__RADIUS'])
        self.indi_allsky_config['UPLOAD_WORKERS']                       = int(request.json['UPLOAD_WORKERS'])
        self.indi_allsky_config['FILETRANSFER']['CLASSNAME']            = str(request.json['FILETRANSFER__CLASSNAME'])
        self.indi_allsky_config['FILETRANSFER']['HOST']                 = str(request.json['FILETRANSFER__HOST'])
        self.indi_allsky_config['FILETRANSFER']['PORT']                 = int(request.json['FILETRANSFER__PORT'])
        self.indi_allsky_config['FILETRANSFER']['USERNAME']             = str(request.json['FILETRANSFER__USERNAME'])
        self.indi_allsky_config['FILETRANSFER']['PASSWORD']             = str(request.json['FILETRANSFER__PASSWORD'])
        self.indi_allsky_config['FILETRANSFER']['PRIVATE_KEY']          = str(request.json['FILETRANSFER__PRIVATE_KEY'])
        self.indi_allsky_config['FILETRANSFER']['PUBLIC_KEY']           = str(request.json['FILETRANSFER__PUBLIC_KEY'])
        self.indi_allsky_config['FILETRANSFER']['TIMEOUT']              = float(request.json['FILETRANSFER__TIMEOUT'])
        self.indi_allsky_config['FILETRANSFER']['CERT_BYPASS']          = bool(request.json['FILETRANSFER__CERT_BYPASS'])
        self.indi_allsky_config['FILETRANSFER']['REMOTE_IMAGE_NAME']        = str(request.json['FILETRANSFER__REMOTE_IMAGE_NAME'])
        self.indi_allsky_config['FILETRANSFER']['REMOTE_IMAGE_FOLDER']      = str(request.json['FILETRANSFER__REMOTE_IMAGE_FOLDER'])
        self.indi_allsky_config['FILETRANSFER']['REMOTE_METADATA_NAME']     = str(request.json['FILETRANSFER__REMOTE_METADATA_NAME'])
        self.indi_allsky_config['FILETRANSFER']['REMOTE_METADATA_FOLDER']   = str(request.json['FILETRANSFER__REMOTE_METADATA_FOLDER'])
        self.indi_allsky_config['FILETRANSFER']['REMOTE_VIDEO_FOLDER']      = str(request.json['FILETRANSFER__REMOTE_VIDEO_FOLDER'])
        self.indi_allsky_config['FILETRANSFER']['REMOTE_KEOGRAM_FOLDER']    = str(request.json['FILETRANSFER__REMOTE_KEOGRAM_FOLDER'])
        self.indi_allsky_config['FILETRANSFER']['REMOTE_STARTRAIL_FOLDER']  = str(request.json['FILETRANSFER__REMOTE_STARTRAIL_FOLDER'])
        self.indi_allsky_config['FILETRANSFER']['REMOTE_ENDOFNIGHT_FOLDER'] = str(request.json['FILETRANSFER__REMOTE_ENDOFNIGHT_FOLDER'])
        self.indi_allsky_config['FILETRANSFER']['UPLOAD_IMAGE']         = int(request.json['FILETRANSFER__UPLOAD_IMAGE'])
        self.indi_allsky_config['FILETRANSFER']['UPLOAD_METADATA']      = bool(request.json['FILETRANSFER__UPLOAD_METADATA'])
        self.indi_allsky_config['FILETRANSFER']['UPLOAD_VIDEO']         = bool(request.json['FILETRANSFER__UPLOAD_VIDEO'])
        self.indi_allsky_config['FILETRANSFER']['UPLOAD_KEOGRAM']       = bool(request.json['FILETRANSFER__UPLOAD_KEOGRAM'])
        self.indi_allsky_config['FILETRANSFER']['UPLOAD_STARTRAIL']     = bool(request.json['FILETRANSFER__UPLOAD_STARTRAIL'])
        self.indi_allsky_config['FILETRANSFER']['UPLOAD_ENDOFNIGHT']    = bool(request.json['FILETRANSFER__UPLOAD_ENDOFNIGHT'])
        self.indi_allsky_config['S3UPLOAD']['CLASSNAME']                = str(request.json['S3UPLOAD__CLASSNAME'])
        self.indi_allsky_config['S3UPLOAD']['ENABLE']                   = bool(request.json['S3UPLOAD__ENABLE'])
        self.indi_allsky_config['S3UPLOAD']['ACCESS_KEY']               = str(request.json['S3UPLOAD__ACCESS_KEY'])
        self.indi_allsky_config['S3UPLOAD']['SECRET_KEY']               = str(request.json['S3UPLOAD__SECRET_KEY'])
        self.indi_allsky_config['S3UPLOAD']['BUCKET']                   = str(request.json['S3UPLOAD__BUCKET'])
        self.indi_allsky_config['S3UPLOAD']['REGION']                   = str(request.json['S3UPLOAD__REGION'])
        self.indi_allsky_config['S3UPLOAD']['HOST']                     = str(request.json['S3UPLOAD__HOST'])
        self.indi_allsky_config['S3UPLOAD']['PORT']                     = int(request.json['S3UPLOAD__PORT'])
        self.indi_allsky_config['S3UPLOAD']['URL_TEMPLATE']             = str(request.json['S3UPLOAD__URL_TEMPLATE'])
        self.indi_allsky_config['S3UPLOAD']['STORAGE_CLASS']            = str(request.json['S3UPLOAD__STORAGE_CLASS'])
        self.indi_allsky_config['S3UPLOAD']['ACL']                      = str(request.json['S3UPLOAD__ACL'])
        self.indi_allsky_config['S3UPLOAD']['EXPIRE_IMAGES']            = bool(request.json['S3UPLOAD__EXPIRE_IMAGES'])
        self.indi_allsky_config['S3UPLOAD']['EXPIRE_TIMELAPSE']         = bool(request.json['S3UPLOAD__EXPIRE_TIMELAPSE'])
        self.indi_allsky_config['S3UPLOAD']['TLS']                      = bool(request.json['S3UPLOAD__TLS'])
        self.indi_allsky_config['S3UPLOAD']['CERT_BYPASS']              = bool(request.json['S3UPLOAD__CERT_BYPASS'])
        self.indi_allsky_config['MQTTPUBLISH']['ENABLE']                = bool(request.json['MQTTPUBLISH__ENABLE'])
        self.indi_allsky_config['MQTTPUBLISH']['TRANSPORT']             = str(request.json['MQTTPUBLISH__TRANSPORT'])
        self.indi_allsky_config['MQTTPUBLISH']['HOST']                  = str(request.json['MQTTPUBLISH__HOST'])
        self.indi_allsky_config['MQTTPUBLISH']['PORT']                  = int(request.json['MQTTPUBLISH__PORT'])
        self.indi_allsky_config['MQTTPUBLISH']['USERNAME']              = str(request.json['MQTTPUBLISH__USERNAME'])
        self.indi_allsky_config['MQTTPUBLISH']['PASSWORD']              = str(request.json['MQTTPUBLISH__PASSWORD'])
        self.indi_allsky_config['MQTTPUBLISH']['BASE_TOPIC']            = str(request.json['MQTTPUBLISH__BASE_TOPIC'])
        self.indi_allsky_config['MQTTPUBLISH']['QOS']                   = int(request.json['MQTTPUBLISH__QOS'])
        self.indi_allsky_config['MQTTPUBLISH']['TLS']                   = bool(request.json['MQTTPUBLISH__TLS'])
        self.indi_allsky_config['MQTTPUBLISH']['CERT_BYPASS']           = bool(request.json['MQTTPUBLISH__CERT_BYPASS'])
        self.indi_allsky_config['SYNCAPI']['ENABLE']                    = bool(request.json['SYNCAPI__ENABLE'])
        self.indi_allsky_config['SYNCAPI']['BASEURL']                   = str(request.json['SYNCAPI__BASEURL'])
        self.indi_allsky_config['SYNCAPI']['USERNAME']                  = str(request.json['SYNCAPI__USERNAME'])
        self.indi_allsky_config['SYNCAPI']['APIKEY']                    = str(request.json['SYNCAPI__APIKEY'])
        self.indi_allsky_config['SYNCAPI']['CERT_BYPASS']               = bool(request.json['SYNCAPI__CERT_BYPASS'])
        self.indi_allsky_config['SYNCAPI']['POST_S3']                   = bool(request.json['SYNCAPI__POST_S3'])
        self.indi_allsky_config['FITSHEADERS'][0][0]                    = str(request.json['FITSHEADERS__0__KEY'])
        self.indi_allsky_config['FITSHEADERS'][0][1]                    = str(request.json['FITSHEADERS__0__VAL'])
        self.indi_allsky_config['FITSHEADERS'][1][0]                    = str(request.json['FITSHEADERS__1__KEY'])
        self.indi_allsky_config['FITSHEADERS'][1][1]                    = str(request.json['FITSHEADERS__1__VAL'])
        self.indi_allsky_config['FITSHEADERS'][2][0]                    = str(request.json['FITSHEADERS__2__KEY'])
        self.indi_allsky_config['FITSHEADERS'][2][1]                    = str(request.json['FITSHEADERS__2__VAL'])
        self.indi_allsky_config['FITSHEADERS'][3][0]                    = str(request.json['FITSHEADERS__3__KEY'])
        self.indi_allsky_config['FITSHEADERS'][3][1]                    = str(request.json['FITSHEADERS__3__VAL'])
        self.indi_allsky_config['FITSHEADERS'][4][0]                    = str(request.json['FITSHEADERS__4__KEY'])
        self.indi_allsky_config['FITSHEADERS'][4][1]                    = str(request.json['FITSHEADERS__4__VAL'])
        self.indi_allsky_config['LIBCAMERA']['IMAGE_FILE_TYPE']         = str(request.json['LIBCAMERA__IMAGE_FILE_TYPE'])
        self.indi_allsky_config['LIBCAMERA']['EXTRA_OPTIONS']           = str(request.json['LIBCAMERA__EXTRA_OPTIONS'])

        self.indi_allsky_config['FILETRANSFER']['LIBCURL_OPTIONS']      = json.loads(str(request.json['FILETRANSFER__LIBCURL_OPTIONS']))
        self.indi_allsky_config['INDI_CONFIG_DEFAULTS']                 = json.loads(str(request.json['INDI_CONFIG_DEFAULTS']))
        self.indi_allsky_config['ENCRYPT_PASSWORDS']                    = bool(request.json['ENCRYPT_PASSWORDS'])

        # Not a config option
        reload_on_save                                                  = bool(request.json['RELOAD_ON_SAVE'])
        config_note                                                     = str(request.json['CONFIG_NOTE'])


        # ADU_ROI
        adu_roi_x1 = int(request.json['ADU_ROI_X1'])
        adu_roi_y1 = int(request.json['ADU_ROI_Y1'])
        adu_roi_x2 = int(request.json['ADU_ROI_X2'])
        adu_roi_y2 = int(request.json['ADU_ROI_Y2'])

        # the x2 and y2 values must be positive integers in order to be enabled and valid
        if adu_roi_x2 and adu_roi_y2:
            self.indi_allsky_config['ADU_ROI'] = [adu_roi_x1, adu_roi_y1, adu_roi_x2, adu_roi_y2]
        else:
            self.indi_allsky_config['ADU_ROI'] = []


        # SQM_ROI
        sqm_roi_x1 = int(request.json['SQM_ROI_X1'])
        sqm_roi_y1 = int(request.json['SQM_ROI_Y1'])
        sqm_roi_x2 = int(request.json['SQM_ROI_X2'])
        sqm_roi_y2 = int(request.json['SQM_ROI_Y2'])

        # the x2 and y2 values must be positive integers in order to be enabled and valid
        if sqm_roi_x2 and sqm_roi_y2:
            self.indi_allsky_config['SQM_ROI'] = [sqm_roi_x1, sqm_roi_y1, sqm_roi_x2, sqm_roi_y2]
        else:
            self.indi_allsky_config['SQM_ROI'] = []


        # IMAGE_CROP_ROI
        image_crop_roi_x1 = int(request.json['IMAGE_CROP_ROI_X1'])
        image_crop_roi_y1 = int(request.json['IMAGE_CROP_ROI_Y1'])
        image_crop_roi_x2 = int(request.json['IMAGE_CROP_ROI_X2'])
        image_crop_roi_y2 = int(request.json['IMAGE_CROP_ROI_Y2'])

        # the x2 and y2 values must be positive integers in order to be enabled and valid
        if image_crop_roi_x2 and image_crop_roi_y2:
            self.indi_allsky_config['IMAGE_CROP_ROI'] = [image_crop_roi_x1, image_crop_roi_y1, image_crop_roi_x2, image_crop_roi_y2]
        else:
            self.indi_allsky_config['IMAGE_CROP_ROI'] = []



        # TEXT_PROPERTIES FONT_COLOR
        font_color_str = str(request.json['TEXT_PROPERTIES__FONT_COLOR'])
        font_r, font_g, font_b = font_color_str.split(',')
        self.indi_allsky_config['TEXT_PROPERTIES']['FONT_COLOR'] = [int(font_r), int(font_g), int(font_b)]

        # ORB_PROPERTIES SUN_COLOR
        sun_color_str = str(request.json['ORB_PROPERTIES__SUN_COLOR'])
        sun_r, sun_g, sun_b = sun_color_str.split(',')
        self.indi_allsky_config['ORB_PROPERTIES']['SUN_COLOR'] = [int(sun_r), int(sun_g), int(sun_b)]

        # ORB_PROPERTIES MOON_COLOR
        moon_color_str = str(request.json['ORB_PROPERTIES__MOON_COLOR'])
        moon_r, moon_g, moon_b = moon_color_str.split(',')
        self.indi_allsky_config['ORB_PROPERTIES']['MOON_COLOR'] = [int(moon_r), int(moon_g), int(moon_b)]


        # save new config
        if not app.config['LOGIN_DISABLED']:
            username = current_user.username
        else:
            username = 'system'


        try:
            self._indi_allsky_config_obj.save(username, config_note)
            app.logger.info('Saved new config')
        except ConfigSaveException as e:
            error_data = {
                'form_global' : [str(e)],
            }
            return jsonify(error_data), 400


        if reload_on_save:
            task_reload = IndiAllSkyDbTaskQueueTable(
                queue=TaskQueueQueue.MAIN,
                state=TaskQueueState.MANUAL,
                data={'action' : 'reload'},
            )

            db.session.add(task_reload)
            db.session.commit()

            message = {
                'success-message' : 'Saved new config,  Reloading indi-allsky service.',
            }
        else:
            message = {
                'success-message' : 'Saved new config',
            }


        return jsonify(message)


class AjaxSetTimeView(BaseView):
    methods = ['POST']
    decorators = [login_required]

    def dispatch_request(self):
        form_settime = IndiAllskySetDateTimeForm(data=request.json)


        if not app.config['LOGIN_DISABLED']:
            if not current_user.is_admin:
                form_errors = form_settime.errors  # this must be a property
                form_errors['form_settime_global'] = ['You do not have permission to make configuration changes']
                return jsonify(form_errors), 400


        if not form_settime.validate():
            form_errors = form_settime.errors  # this must be a property
            form_errors['form_settime_global'] = ['Please fix the errors above']
            return jsonify(form_errors), 400


        new_datetime_str = str(request.json['NEW_DATETIME'])
        new_datetime = datetime.strptime(new_datetime_str, '%Y-%m-%dT%H:%M:%S')

        new_datetime_utc = new_datetime.astimezone(tz=timezone.utc)


        try:
            self.setTimeSystemd(new_datetime_utc)
        except dbus.exceptions.DBusException as e:
            # manually build this error
            form_errors = {
                'form_settime_global' : [str(e)],
            }
            return jsonify(form_errors), 400

        # form passed validation
        message = {
            'success-message' : 'System time updated',
        }


        #systemtime_utc = datetime.utcnow()

        #time_offset = systemtime_utc.timestamp() - new_datetime_utc.timestamp()
        #app.logger.info('Time offset: %ds', int(time_offset))

        #task_settime = IndiAllSkyDbTaskQueueTable(
        #    queue=TaskQueueQueue.MAIN,
        #    state=TaskQueueState.MANUAL,
        #    data={
        #        'action'      : 'settime',
        #        'time_offset' : time_offset,
        #    },
        #)

        #db.session.add(task_settime)
        #db.session.commit()

        ## form passed validation
        #message = {
        #    'success-message' : 'System time update queued.',
        #}

        return jsonify(message)


    def setTimeSystemd(self, new_datetime_utc):
        epoch = new_datetime_utc.timestamp() + 5  # add 5 due to sleep below
        epoch_msec = epoch * 1000000

        system_bus = dbus.SystemBus()
        timedate1 = system_bus.get_object('org.freedesktop.timedate1', '/org/freedesktop/timedate1')
        manager = dbus.Interface(timedate1, 'org.freedesktop.timedate1')

        app.logger.warning('Disabling NTP time sync')
        manager.SetNTP(False, False)  # disable time sync
        time.sleep(5.0)  # give enough time for time sync to diable

        r2 = manager.SetTime(epoch_msec, False, False)

        return r2


class ImageViewerView(FormView):
    def get_context(self):
        context = super(ImageViewerView, self).get_context()

        form_data = {
            'YEAR_SELECT'  : None,
            'MONTH_SELECT' : None,
            'DAY_SELECT'   : None,
            'HOUR_SELECT'  : None,
            'FILTER_DETECTIONS' : None,
        }

        context['form_viewer'] = IndiAllskyImageViewerPreload(
            data=form_data,
            camera_id=session['camera_id'],
            s3_prefix=self.s3_prefix,
            non_local=self.indi_allsky_config['WEB_NONLOCAL_IMAGES'],
        )

        return context



class AjaxImageViewerView(BaseView):
    methods = ['POST']

    def __init__(self, **kwargs):
        super(AjaxImageViewerView, self).__init__(**kwargs)


    def dispatch_request(self):
        form_year  = request.json.get('YEAR_SELECT')
        form_month = request.json.get('MONTH_SELECT')
        form_day   = request.json.get('DAY_SELECT')
        form_hour  = request.json.get('HOUR_SELECT')
        form_filter_detections = bool(request.json.get('FILTER_DETECTIONS'))

        if form_filter_detections:
            # filter images that have a detection
            form_viewer = IndiAllskyImageViewer(
                data=request.json,
                camera_id=session['camera_id'],
                detections_count=1,
                s3_prefix=self.s3_prefix,
                non_local=self.indi_allsky_config['WEB_NONLOCAL_IMAGES'],
            )
        else:
            form_viewer = IndiAllskyImageViewer(
                data=request.json,
                camera_id=session['camera_id'],
                detections_count=0,
                s3_prefix=self.s3_prefix,
                non_local=self.indi_allsky_config['WEB_NONLOCAL_IMAGES'],
            )


        json_data = {}


        if form_hour:
            form_datetime = datetime.strptime('{0} {1} {2} {3}'.format(form_year, form_month, form_day, form_hour), '%Y %m %d %H')

            year = form_datetime.strftime('%Y')
            month = form_datetime.strftime('%m')
            day = form_datetime.strftime('%d')
            hour = form_datetime.strftime('%H')

            img_select, fits_select, raw_select = form_viewer.getImages(year, month, day, hour)
            json_data['IMG_SELECT'] = img_select
            json_data['FITS_SELECT'] = fits_select
            json_data['RAW_SELECT'] = raw_select


        elif form_day:
            form_datetime = datetime.strptime('{0} {1} {2}'.format(form_year, form_month, form_day), '%Y %m %d')

            year = form_datetime.strftime('%Y')
            month = form_datetime.strftime('%m')
            day = form_datetime.strftime('%d')

            json_data['HOUR_SELECT'] = form_viewer.getHours(year, month, day)
            hour = json_data['HOUR_SELECT'][0][0]

            img_select, fits_select, raw_select = form_viewer.getImages(year, month, day, hour)
            json_data['IMG_SELECT'] = img_select
            json_data['FITS_SELECT'] = fits_select
            json_data['RAW_SELECT'] = raw_select

        elif form_month:
            form_datetime = datetime.strptime('{0} {1}'.format(form_year, form_month), '%Y %m')

            year = form_datetime.strftime('%Y')
            month = form_datetime.strftime('%m')

            json_data['DAY_SELECT'] = form_viewer.getDays(year, month)
            day = json_data['DAY_SELECT'][0][0]

            json_data['HOUR_SELECT'] = form_viewer.getHours(year, month, day)
            hour = json_data['HOUR_SELECT'][0][0]

            img_select, fits_select, raw_select = form_viewer.getImages(year, month, day, hour)
            json_data['IMG_SELECT'] = img_select
            json_data['FITS_SELECT'] = fits_select
            json_data['RAW_SELECT'] = raw_select

        elif form_year:
            form_datetime = datetime.strptime('{0}'.format(form_year), '%Y')

            year = form_datetime.strftime('%Y')

            json_data['MONTH_SELECT'] = form_viewer.getMonths(year)
            month = json_data['MONTH_SELECT'][0][0]

            json_data['DAY_SELECT'] = form_viewer.getDays(year, month)
            day = json_data['DAY_SELECT'][0][0]

            json_data['HOUR_SELECT'] = form_viewer.getHours(year, month, day)
            hour = json_data['HOUR_SELECT'][0][0]

            img_select, fits_select, raw_select = form_viewer.getImages(year, month, day, hour)
            json_data['IMG_SELECT'] = img_select
            json_data['FITS_SELECT'] = fits_select
            json_data['RAW_SELECT'] = raw_select

        else:
            # this happens when filtering images on detections
            json_data['YEAR_SELECT'] = form_viewer.getYears()

            if not json_data['YEAR_SELECT']:
                # No images returned
                json_data['YEAR_SELECT'] = (('', None),)
                json_data['MONTH_SELECT'] = (('', None),)
                json_data['DAY_SELECT'] = (('', None),)
                json_data['HOUR_SELECT'] = (('', None),)
                json_data['IMG_SELECT'] = (('', None),)
                json_data['FITS_SELECT'] = (('', None),)
                json_data['RAW_SELECT'] = (('', None),)

                return json_data


            year = json_data['YEAR_SELECT'][0][0]

            json_data['MONTH_SELECT'] = form_viewer.getMonths(year)
            month = json_data['MONTH_SELECT'][0][0]

            json_data['DAY_SELECT'] = form_viewer.getDays(year, month)
            day = json_data['DAY_SELECT'][0][0]

            json_data['HOUR_SELECT'] = form_viewer.getHours(year, month, day)
            hour = json_data['HOUR_SELECT'][0][0]

            img_select, fits_select, raw_select = form_viewer.getImages(year, month, day, hour)
            json_data['IMG_SELECT'] = img_select
            json_data['FITS_SELECT'] = fits_select
            json_data['RAW_SELECT'] = raw_select


        return jsonify(json_data)


class VideoViewerView(FormView):
    def get_context(self):
        context = super(VideoViewerView, self).get_context()

        form_data = {
            'YEAR_SELECT'  : None,
            'MONTH_SELECT' : None,
        }

        context['form_video_viewer'] = IndiAllskyVideoViewerPreload(
            data=form_data,
            camera_id=session['camera_id'],
            s3_prefix=self.s3_prefix,
            non_local=self.indi_allsky_config['WEB_NONLOCAL_IMAGES'],
        )

        return context


class AjaxVideoViewerView(BaseView):
    methods = ['POST']

    def __init__(self, **kwargs):
        super(AjaxVideoViewerView, self).__init__(**kwargs)


    def dispatch_request(self):
        form_video_viewer = IndiAllskyVideoViewer(
            data=request.json,
            camera_id=session['camera_id'],
            s3_prefix=self.s3_prefix,
            non_local=self.indi_allsky_config['WEB_NONLOCAL_IMAGES'],
        )


        form_year      = request.json.get('YEAR_SELECT')
        form_month     = request.json.get('MONTH_SELECT')
        form_timeofday = request.json.get('TIMEOFDAY_SELECT')

        json_data = {}

        if form_month:
            form_datetime = datetime.strptime('{0} {1}'.format(form_year, form_month), '%Y %m')

            year = form_datetime.strftime('%Y')
            month = form_datetime.strftime('%m')

            json_data['video_list'] = form_video_viewer.getVideos(year, month, form_timeofday)

        elif form_year:
            form_datetime = datetime.strptime('{0}'.format(form_year), '%Y')

            year = form_datetime.strftime('%Y')

            json_data['MONTH_SELECT'] = form_video_viewer.getMonths(year)
            month = json_data['MONTH_SELECT'][0][0]

            json_data['video_list'] = form_video_viewer.getVideos(year, month, form_timeofday)

        return jsonify(json_data)


class SystemInfoView(TemplateView):
    decorators = [login_required]

    def get_context(self):
        context = super(SystemInfoView, self).get_context()

        context['release'] = str(__version__)

        context['uptime_str'] = self.getUptime()

        context['cpu_count'] = self.getCpuCount()
        context['cpu_usage'] = self.getCpuUsage()

        load5, load10, load15 = self.getLoadAverage()
        context['cpu_load5'] = load5
        context['cpu_load10'] = load10
        context['cpu_load15'] = load15

        mem_total, mem_usage = self.getMemoryUsage()
        context['mem_total'] = mem_total
        context['mem_usage'] = mem_usage

        context['swap_usage'] = self.getSwapUsage()

        context['fs_data'] = self.getAllFsUsage()

        context['temp_list'] = self.getTemps()

        context['net_list'] = self.getNetworkIps()

        context['indiserver_service'] = self.getSystemdUnitStatus(app.config['INDISERVER_SERVICE_NAME'])
        context['indi_allsky_service'] = self.getSystemdUnitStatus(app.config['ALLSKY_SERVICE_NAME'])
        context['gunicorn_indi_allsky_service'] = self.getSystemdUnitStatus(app.config['GUNICORN_SERVICE_NAME'])

        context['python_version'] = platform.python_version()
        context['python_platform'] = platform.machine()

        context['cv2_version'] = str(getattr(cv2, '__version__', -1))
        context['ephem_version'] = str(getattr(ephem, '__version__', -1))
        context['numpy_version'] = str(getattr(numpy, '__version__', -1))
        context['astropy_version'] = str(getattr(astropy, '__version__', -1))
        context['flask_version'] = str(getattr(flask, '__version__', -1))
        context['dbus_version'] = str(getattr(dbus, '__version__', -1))
        context['paramiko_version'] = str(getattr(paramiko, '__version__', -1))
        context['pycurl_version'] = str(getattr(pycurl, 'version', -1))
        context['pahomqtt_version'] = str(getattr(paho.mqtt, '__version__', -1))
        context['ccdproc_version'] = str(getattr(ccdproc, '__version__', -1))
        context['pyindi_version'] = '.'.join((
            str(getattr(PyIndi, 'INDI_VERSION_MAJOR', -1)),
            str(getattr(PyIndi, 'INDI_VERSION_MINOR', -1)),
            str(getattr(PyIndi, 'INDI_VERSION_RELEASE', -1)),
        ))


        context['now'] = datetime.now()
        context['form_settime'] = IndiAllskySetDateTimeForm()
        context['timedate1_dict'] = self.getSystemdTimeDate()

        return context


    def getUptime(self):
        uptime_s = time.time() - psutil.boot_time()

        days = int(uptime_s / 86400)
        uptime_s -= (days * 86400)

        hours = int(uptime_s / 3600)
        uptime_s -= (hours * 3600)

        minutes = int(uptime_s / 60)
        uptime_s -= (minutes * 60)

        seconds = int(uptime_s)

        uptime_str = '{0:d} days, {1:d} hours, {2:d} minutes, {3:d} seconds'.format(days, hours, minutes, seconds)

        return uptime_str


    def getCpuCount(self):
        return psutil.cpu_count()


    def getCpuUsage(self):
        c = psutil.cpu_times_percent()

        cpu_percent = {
            'user'    : c.user,
            'system'  : c.system,
            'idle'    : c.idle,
            'nice'    : c.nice,
            'iowait'  : c.iowait,
            'irq'     : c.irq,
            'softirq' : c.softirq,
        }

        return cpu_percent


    def getLoadAverage(self):
        return psutil.getloadavg()


    def getMemoryUsage(self):
        memory_info = psutil.virtual_memory()

        memory_total = memory_info.total
        #memory_free = memory_info.free

        memory_percent = {
            'user_percent'    : (memory_info.used / memory_total) * 100.0,
            'cached_percent'  : (memory_info.cached / memory_total) * 100.0,
        }

        memory_total_mb = int(memory_total / 1024.0 / 1024.0)

        #memory_percent = 100 - ((memory_free * 100) / memory_total)

        return memory_total_mb, memory_percent


    def getSwapUsage(self):
        swap_info = psutil.swap_memory()

        return swap_info[3]


    def getAllFsUsage(self):
        fs_list = psutil.disk_partitions()

        fs_data = list()
        for fs in fs_list:
            if fs.mountpoint.startswith('/snap/'):
                # skip snap filesystems
                continue

            disk_usage = psutil.disk_usage(fs.mountpoint)

            data = {
                'total_mb'   : disk_usage.total / 1024.0 / 1024.0,
                'mountpoint' : fs.mountpoint,
                'percent'    : disk_usage.percent,
            }

            fs_data.append(data)

        return fs_data


    def getTemps(self):
        temp_info = psutil.sensors_temperatures()

        temp_list = list()
        for t_key in temp_info.keys():
            for i, t in enumerate(temp_info[t_key]):
                if self.indi_allsky_config.get('TEMP_DISPLAY') == 'f':
                    current_temp = ((t.current * 9.0 ) / 5.0) + 32
                    temp_sys = 'F'
                elif self.indi_allsky_config.get('TEMP_DISPLAY') == 'k':
                    current_temp = t.current + 273.15
                    temp_sys = 'K'
                else:
                    current_temp = float(t.current)
                    temp_sys = 'C'

                # these names will match the mqtt topics
                if not t.label:
                    # use index for label name
                    label = str(i)
                else:
                    label = t.label

                topic = '{0:s}/{1:s}'.format(t_key, label)

                # no spaces, etc in topics
                topic_sub = re.sub(r'[#+\$\*\>\ ]', '_', topic)

                temp_list.append({
                    'name'   : topic_sub,
                    'temp'   : current_temp,
                    'sys'    : temp_sys,
                })

        return temp_list


    def getNetworkIps(self):
        net_info = psutil.net_if_addrs()

        net_list = list()
        for dev, addr_info in net_info.items():
            if dev == 'lo':
                # skip loopback
                continue


            dev_info = {
                'name'  : dev,
                'inet4' : [],
                'inet6' : [],
            }

            for addr in addr_info:
                if addr.family == socket.AF_INET:
                    dev_info['inet4'].append(addr.address)

                elif addr.family == socket.AF_INET6:
                    dev_info['inet6'].append(addr.address)

            net_list.append(dev_info)


        return net_list


    def getSystemdUnitStatus(self, unit):
        session_bus = dbus.SessionBus()
        systemd1 = session_bus.get_object('org.freedesktop.systemd1', '/org/freedesktop/systemd1')
        manager = dbus.Interface(systemd1, 'org.freedesktop.systemd1.Manager')

        try:
            service = session_bus.get_object('org.freedesktop.systemd1', object_path=manager.GetUnit(unit))
        except dbus.exceptions.DBusException:
            return 'UNKNOWN'

        interface = dbus.Interface(service, dbus_interface='org.freedesktop.DBus.Properties')
        unit_state = interface.Get('org.freedesktop.systemd1.Unit', 'ActiveState')

        return str(unit_state)


    def getSystemdTimeDate(self):
        session_bus = dbus.SystemBus()
        timedate1 = session_bus.get_object('org.freedesktop.timedate1', '/org/freedesktop/timedate1')
        manager = dbus.Interface(timedate1, 'org.freedesktop.DBus.Properties')

        timedate1_dict = dict()
        timedate1_dict['Timezone'] = str(manager.Get('org.freedesktop.timedate1', 'Timezone'))
        timedate1_dict['CanNTP'] = bool(manager.Get('org.freedesktop.timedate1', 'CanNTP'))
        timedate1_dict['NTP'] = bool(manager.Get('org.freedesktop.timedate1', 'NTP'))
        timedate1_dict['NTPSynchronized'] = bool(manager.Get('org.freedesktop.timedate1', 'NTPSynchronized'))
        timedate1_dict['LocalRTC'] = bool(manager.Get('org.freedesktop.timedate1', 'LocalRTC'))
        timedate1_dict['TimeUSec'] = int(manager.Get('org.freedesktop.timedate1', 'TimeUSec'))

        #app.logger.info('timedate1: %s', timedate1_dict)

        return timedate1_dict



class TaskQueueView(TemplateView):
    decorators = [login_required]

    def get_context(self):
        context = super(TaskQueueView, self).get_context()

        state_list = (
            TaskQueueState.MANUAL,
            TaskQueueState.QUEUED,
            TaskQueueState.RUNNING,
            TaskQueueState.SUCCESS,
            TaskQueueState.FAILED,
        )

        exclude_queues = (
            TaskQueueQueue.IMAGE,
            TaskQueueQueue.UPLOAD,
        )

        now_minus_3d = datetime.now() - timedelta(days=3)

        tasks = IndiAllSkyDbTaskQueueTable.query\
            .filter(
                and_(
                    IndiAllSkyDbTaskQueueTable.createDate > now_minus_3d,
                    IndiAllSkyDbTaskQueueTable.state.in_(state_list),
                    ~IndiAllSkyDbTaskQueueTable.queue.in_(exclude_queues),
                )
            )\
            .order_by(IndiAllSkyDbTaskQueueTable.createDate.desc())


        task_list = list()
        for task in tasks:
            t = {
                'id'         : task.id,
                'createDate' : task.createDate,
                'queue'      : task.queue.name,
                'state'      : task.state.name,
                'result'     : task.result,
            }

            task_list.append(t)

        context['task_list'] = task_list

        return context


class AjaxSystemInfoView(BaseView):
    methods = ['POST']
    decorators = [login_required]

    def dispatch_request(self):
        form_system = IndiAllskySystemInfoForm(data=request.json)


        if not app.config['LOGIN_DISABLED']:
            if not current_user.is_admin:
                form_errors = form_system.errors  # this must be a property
                form_errors['form_global'] = ['You do not have permission to make configuration changes']
                return jsonify(form_errors), 400


        if not form_system.validate():
            form_errors = form_system.errors  # this must be a property
            return jsonify(form_errors), 400


        service = request.json['SERVICE_HIDDEN']
        command = request.json['COMMAND_HIDDEN']

        if service == app.config['INDISERVER_SERVICE_NAME']:
            if command == 'stop':
                r = self.stopSystemdUnit(app.config['INDISERVER_SERVICE_NAME'])
            elif command == 'start':
                r = self.startSystemdUnit(app.config['INDISERVER_SERVICE_NAME'])
            else:
                errors_data = {
                    'COMMAND_HIDDEN' : ['Unhandled command'],
                }
                return jsonify(errors_data), 400


        elif service == app.config['ALLSKY_SERVICE_NAME']:
            if command == 'hup':
                task_reload = IndiAllSkyDbTaskQueueTable(
                    queue=TaskQueueQueue.MAIN,
                    state=TaskQueueState.MANUAL,
                    data={'action' : 'reload'},
                )

                db.session.add(task_reload)
                db.session.commit()

                r = 'Submitted reload task'

                #r = self.hupSystemdUnit(app.config['ALLSKY_SERVICE_NAME'])
            elif command == 'stop':
                r = self.stopSystemdUnit(app.config['ALLSKY_SERVICE_NAME'])
            elif command == 'start':
                r = self.startSystemdUnit(app.config['ALLSKY_SERVICE_NAME'])
            else:
                errors_data = {
                    'COMMAND_HIDDEN' : ['Unhandled command'],
                }
                return jsonify(errors_data), 400


        elif service == app.config['GUNICORN_SERVICE_NAME']:
            if command == 'stop':
                r = self.stopSystemdUnit(app.config['GUNICORN_SERVICE_NAME'])
            else:
                errors_data = {
                    'COMMAND_HIDDEN' : ['Unhandled command'],
                }
                return jsonify(errors_data), 400


        elif service == 'system':
            if command == 'reboot':
                # allowing rebooting from non-admin networks for now
                r = self.rebootSystemd()
            elif command == 'poweroff':
                if not self.verify_admin_network():
                    json_data = {
                        'form_global' : ['Request not from admin network (flask.json)'],
                    }
                    return jsonify(json_data), 400

                r = self.poweroffSystemd()

            elif command == 'validate_db':
                message_list = self.validateDbEntries()

                json_data = {
                    'success-message' : ''.join(message_list),
                }
                return jsonify(json_data)
            elif command == 'flush_images':
                if not self.verify_admin_network():
                    json_data = {
                        'form_global' : ['Request not from admin network (flask.json)'],
                    }
                    return jsonify(json_data), 400

                image_count = self.flushImages(session['camera_id'])

                json_data = {
                    'success-message' : '{0:d} Images Deleted'.format(image_count),
                }
                return jsonify(json_data)
            elif command == 'flush_timelapses':
                if not self.verify_admin_network():
                    json_data = {
                        'form_global' : ['Request not from admin network (flask.json)'],
                    }
                    return jsonify(json_data), 400


                file_count = self.flushTimelapses(session['camera_id'])

                json_data = {
                    'success-message' : '{0:d} Files Deleted'.format(file_count),
                }
                return jsonify(json_data)
            else:
                errors_data = {
                    'COMMAND_HIDDEN' : ['Unhandled command'],
                }
                return jsonify(errors_data), 400


        else:
            errors_data = {
                'SERVICE_HIDDEN' : ['Unhandled service'],
            }
            return jsonify(errors_data), 400


        app.logger.info('Command return: %s', str(r))

        json_data = {
            'success-message' : 'Job submitted',
        }

        return jsonify(json_data)


    def stopSystemdUnit(self, unit):
        session_bus = dbus.SessionBus()
        systemd1 = session_bus.get_object('org.freedesktop.systemd1', '/org/freedesktop/systemd1')
        manager = dbus.Interface(systemd1, 'org.freedesktop.systemd1.Manager')
        r = manager.StopUnit(unit, 'fail')

        return r


    def startSystemdUnit(self, unit):
        session_bus = dbus.SessionBus()
        systemd1 = session_bus.get_object('org.freedesktop.systemd1', '/org/freedesktop/systemd1')
        manager = dbus.Interface(systemd1, 'org.freedesktop.systemd1.Manager')
        r = manager.StartUnit(unit, 'fail')

        return r


    def hupSystemdUnit(self, unit):
        session_bus = dbus.SessionBus()
        systemd1 = session_bus.get_object('org.freedesktop.systemd1', '/org/freedesktop/systemd1')
        manager = dbus.Interface(systemd1, 'org.freedesktop.systemd1.Manager')
        r = manager.ReloadUnit(unit, 'fail')

        return r


    def rebootSystemd(self):
        system_bus = dbus.SystemBus()
        systemd1 = system_bus.get_object('org.freedesktop.login1', '/org/freedesktop/login1')
        manager = dbus.Interface(systemd1, 'org.freedesktop.login1.Manager')
        r = manager.Reboot(False)

        return r


    def poweroffSystemd(self):
        system_bus = dbus.SystemBus()
        systemd1 = system_bus.get_object('org.freedesktop.login1', '/org/freedesktop/login1')
        manager = dbus.Interface(systemd1, 'org.freedesktop.login1.Manager')
        r = manager.PowerOff(False)

        return r


    def flushImages(self, camera_id):
        file_count = 0

        ### Images
        image_query = IndiAllSkyDbImageTable.query\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)

        file_count += image_query.count()

        for i in image_query:
            i.deleteAsset()
            db.session.delete(i)

        db.session.commit()


        ### FITS Images
        fits_image_query = IndiAllSkyDbFitsImageTable.query\
            .join(IndiAllSkyDbFitsImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)

        file_count += fits_image_query.count()

        for i in fits_image_query:
            i.deleteAsset()
            db.session.delete(i)

        db.session.commit()


        ### RAW Images
        raw_image_query = IndiAllSkyDbRawImageTable.query\
            .join(IndiAllSkyDbRawImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)

        file_count += raw_image_query.count()

        for i in raw_image_query:
            i.deleteAsset()
            db.session.delete(i)

        db.session.commit()


        return file_count


    def flushTimelapses(self, camera_id):
        video_query = IndiAllSkyDbVideoTable.query\
            .join(IndiAllSkyDbVideoTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)

        keogram_query = IndiAllSkyDbKeogramTable.query\
            .join(IndiAllSkyDbKeogramTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)

        startrail_query = IndiAllSkyDbStarTrailsTable.query\
            .join(IndiAllSkyDbStarTrailsTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)

        startrail_video_query = IndiAllSkyDbStarTrailsVideoTable.query\
            .join(IndiAllSkyDbStarTrailsVideoTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)

        video_count = video_query.count()
        keogram_count = keogram_query.count()
        startrail_count = startrail_query.count()
        startrail_video_count = startrail_video_query.count()

        file_count = video_count + keogram_count + startrail_count + startrail_video_count


        # videos
        for v in video_query:
            v.deleteAsset()
            db.session.delete(v)

        db.session.commit()


        # keograms
        for k in keogram_query:
            k.deleteAsset()
            db.session.delete(k)

        db.session.commit()


        # startrails
        for s in startrail_query:
            s.deleteAsset()
            db.session.delete(s)

        db.session.commit()


        # startrail videos
        for sv in startrail_video_query:
            sv.deleteAsset()
            db.session.delete(sv)

        db.session.commit()


        return file_count


    def validateDbEntries(self):
        message_list = list()

        ### Images
        image_entries = IndiAllSkyDbImageTable.query\
            .filter(IndiAllSkyDbImageTable.s3_key == sa_null())\
            .order_by(IndiAllSkyDbImageTable.createDate.asc())


        image_entries_count = image_entries.count()
        message_list.append('<p>Images: {0:d}</p>'.format(image_entries_count))

        app.logger.info('Searching %d images...', image_entries_count)
        image_notfound_list = list()
        for i in image_entries:
            if not i.validateFile():
                #logger.warning('Entry not found on filesystem: %s', i.filename)
                image_notfound_list.append(i)


        ### FITS Images
        fits_image_entries = IndiAllSkyDbFitsImageTable.query\
            .filter(IndiAllSkyDbFitsImageTable.s3_key == sa_null())\
            .order_by(IndiAllSkyDbFitsImageTable.createDate.asc())


        fits_image_entries_count = fits_image_entries.count()
        message_list.append('<p>FITS Images: {0:d}</p>'.format(fits_image_entries_count))

        app.logger.info('Searching %d fits images...', fits_image_entries_count)
        fits_image_notfound_list = list()
        for i in fits_image_entries:
            if not i.validateFile():
                #logger.warning('Entry not found on filesystem: %s', i.filename)
                fits_image_notfound_list.append(i)


        ### Raw Images
        raw_image_entries = IndiAllSkyDbRawImageTable.query\
            .filter(IndiAllSkyDbRawImageTable.s3_key == sa_null())\
            .order_by(IndiAllSkyDbRawImageTable.createDate.asc())


        raw_image_entries_count = raw_image_entries.count()
        message_list.append('<p>RAW Images: {0:d}</p>'.format(raw_image_entries_count))

        app.logger.info('Searching %d raw images...', raw_image_entries_count)
        raw_image_notfound_list = list()
        for i in raw_image_entries:
            if not i.validateFile():
                #logger.warning('Entry not found on filesystem: %s', i.filename)
                raw_image_notfound_list.append(i)


        ### Bad Pixel Maps
        badpixelmap_entries = IndiAllSkyDbBadPixelMapTable.query\
            .order_by(IndiAllSkyDbBadPixelMapTable.createDate.asc())
        # fixme - need deal with non-local installs


        badpixelmap_entries_count = badpixelmap_entries.count()
        message_list.append('<p>Bad pixel maps: {0:d}</p>'.format(badpixelmap_entries_count))

        app.logger.info('Searching %d bad pixel maps...', badpixelmap_entries_count)
        badpixelmap_notfound_list = list()
        for b in badpixelmap_entries:
            if not b.validateFile():
                #logger.warning('Entry not found on filesystem: %s', b.filename)
                badpixelmap_notfound_list.append(b)


        ### Dark frames
        darkframe_entries = IndiAllSkyDbDarkFrameTable.query\
            .order_by(IndiAllSkyDbDarkFrameTable.createDate.asc())
        # fixme - need deal with non-local installs


        darkframe_entries_count = darkframe_entries.count()
        message_list.append('<p>Dark Frames: {0:d}</p>'.format(darkframe_entries_count))

        app.logger.info('Searching %d dark frames...', darkframe_entries_count)
        darkframe_notfound_list = list()
        for d in darkframe_entries:
            if not d.validateFile():
                #logger.warning('Entry not found on filesystem: %s', d.filename)
                darkframe_notfound_list.append(d)


        ### Videos
        video_entries = IndiAllSkyDbVideoTable.query\
            .filter(
                and_(
                    IndiAllSkyDbVideoTable.success == sa_true(),
                    IndiAllSkyDbVideoTable.s3_key == sa_null(),
                )
            )\
            .order_by(IndiAllSkyDbVideoTable.createDate.asc())

        video_entries_count = video_entries.count()
        message_list.append('<p>Timelapses: {0:d}</p>'.format(video_entries_count))

        app.logger.info('Searching %d videos...', video_entries_count)
        video_notfound_list = list()
        for v in video_entries:
            if not v.validateFile():
                #logger.warning('Entry not found on filesystem: %s', v.filename)
                video_notfound_list.append(v)


        ### Keograms
        keogram_entries = IndiAllSkyDbKeogramTable.query\
            .filter(IndiAllSkyDbKeogramTable.s3_key == sa_null())\
            .order_by(IndiAllSkyDbKeogramTable.createDate.asc())

        keogram_entries_count = keogram_entries.count()
        message_list.append('<p>Keograms: {0:d}</p>'.format(keogram_entries_count))

        app.logger.info('Searching %d keograms...', keogram_entries_count)
        keogram_notfound_list = list()
        for k in keogram_entries:
            if not k.validateFile():
                #logger.warning('Entry not found on filesystem: %s', k.filename)
                keogram_notfound_list.append(k)


        ### Startrails
        startrail_entries = IndiAllSkyDbStarTrailsTable.query\
            .filter(
                and_(
                    IndiAllSkyDbStarTrailsTable.success == sa_true(),
                    IndiAllSkyDbStarTrailsTable.s3_key == sa_null(),
                )
            )\
            .order_by(IndiAllSkyDbStarTrailsTable.createDate.asc())

        startrail_entries_count = startrail_entries.count()
        message_list.append('<p>Star trails: {0:d}</p>'.format(startrail_entries_count))

        app.logger.info('Searching %d star trails...', startrail_entries_count)
        startrail_notfound_list = list()
        for s in startrail_entries:
            if not s.validateFile():
                #logger.warning('Entry not found on filesystem: %s', s.filename)
                startrail_notfound_list.append(s)


        ### Startrail videos
        startrail_video_entries = IndiAllSkyDbStarTrailsVideoTable.query\
            .filter(
                and_(
                    IndiAllSkyDbStarTrailsVideoTable.success == sa_true(),
                    IndiAllSkyDbStarTrailsVideoTable.s3_key == sa_null(),
                )
            )\
            .order_by(IndiAllSkyDbStarTrailsVideoTable.createDate.asc())

        startrail_video_entries_count = startrail_video_entries.count()
        message_list.append('<p>Star trail timelapses: {0:d}</p>'.format(startrail_video_entries_count))

        app.logger.info('Searching %d star trail timelapses...', startrail_video_entries_count)
        startrail_video_notfound_list = list()
        for s in startrail_video_entries:
            if not s.validateFile():
                #logger.warning('Entry not found on filesystem: %s', s.filename)
                startrail_video_notfound_list.append(s)



        app.logger.warning('Images not found: %d', len(image_notfound_list))
        app.logger.warning('FITS Images not found: %d', len(fits_image_notfound_list))
        app.logger.warning('RAW Images not found: %d', len(raw_image_notfound_list))
        app.logger.warning('Bad pixel maps not found: %d', len(badpixelmap_notfound_list))
        app.logger.warning('Dark frames not found: %d', len(darkframe_notfound_list))
        app.logger.warning('Videos not found: %d', len(video_notfound_list))
        app.logger.warning('Keograms not found: %d', len(keogram_notfound_list))
        app.logger.warning('Star trails not found: %d', len(startrail_notfound_list))
        app.logger.warning('Star trail timelapses not found: %d', len(startrail_video_notfound_list))


        ### DELETE ###
        message_list.append('<p>Removed {0:d} missing image entries</p>'.format(len(image_notfound_list)))
        [db.session.delete(i) for i in image_notfound_list]


        message_list.append('<p>Removed {0:d} missing FITS image entries</p>'.format(len(fits_image_notfound_list)))
        [db.session.delete(i) for i in fits_image_notfound_list]


        message_list.append('<p>Removed {0:d} missing RAW image entries</p>'.format(len(raw_image_notfound_list)))
        [db.session.delete(i) for i in raw_image_notfound_list]


        message_list.append('<p>Removed {0:d} missing bad pixel map entries</p>'.format(len(badpixelmap_notfound_list)))
        [db.session.delete(b) for b in badpixelmap_notfound_list]


        message_list.append('<p>Removed {0:d} missing dark frame entries</p>'.format(len(darkframe_notfound_list)))
        [db.session.delete(d) for d in darkframe_notfound_list]


        message_list.append('<p>Removed {0:d} missing video entries</p>'.format(len(video_notfound_list)))
        [db.session.delete(v) for v in video_notfound_list]


        message_list.append('<p>Removed {0:d} missing keogram entries</p>'.format(len(keogram_notfound_list)))
        [db.session.delete(k) for k in keogram_notfound_list]


        message_list.append('<p>Removed {0:d} missing star trail entries</p>'.format(len(startrail_notfound_list)))
        [db.session.delete(s) for s in startrail_notfound_list]


        message_list.append('<p>Removed {0:d} missing star trail timelapse entries</p>'.format(len(startrail_video_notfound_list)))
        [db.session.delete(s) for s in startrail_video_notfound_list]


        # finalize transaction
        db.session.commit()

        return message_list


class TimelapseGeneratorView(TemplateView):
    decorators = [login_required]

    def __init__(self, **kwargs):
        super(TimelapseGeneratorView, self).__init__(**kwargs)


    def get_context(self):
        context = super(TimelapseGeneratorView, self).get_context()

        context['form_timelapsegen'] = IndiAllskyTimelapseGeneratorForm(camera_id=session['camera_id'])

        # Lookup tasks
        state_list = (
            TaskQueueState.MANUAL,
            TaskQueueState.QUEUED,
            TaskQueueState.RUNNING,
            TaskQueueState.SUCCESS,
            TaskQueueState.FAILED,
        )

        queue_list = (
            TaskQueueQueue.VIDEO,
        )

        now_minus_12h = datetime.now() - timedelta(hours=12)

        tasks = IndiAllSkyDbTaskQueueTable.query\
            .filter(
                and_(
                    IndiAllSkyDbTaskQueueTable.createDate > now_minus_12h,
                    IndiAllSkyDbTaskQueueTable.state.in_(state_list),
                    IndiAllSkyDbTaskQueueTable.queue.in_(queue_list),
                )
            )\
            .order_by(IndiAllSkyDbTaskQueueTable.createDate.desc())


        task_list = list()
        for task in tasks:
            t = {
                'id'         : task.id,
                'createDate' : task.createDate,
                'queue'      : task.queue.name,
                'state'      : task.state.name,
                'result'     : task.result,
            }

            task_list.append(t)

        context['task_list'] = task_list


        return context



class AjaxTimelapseGeneratorView(BaseView):
    methods = ['POST']
    decorators = [login_required]


    def __init__(self, **kwargs):
        super(AjaxTimelapseGeneratorView, self).__init__(**kwargs)


    def dispatch_request(self):
        form_timelapsegen = IndiAllskyTimelapseGeneratorForm(data=request.json, camera_id=session['camera_id'])

        if not form_timelapsegen.validate():
            form_errors = form_timelapsegen.errors  # this must be a property
            return jsonify(form_errors), 400


        if not self.verify_admin_network():
            json_data = {
                'form_global' : ['Request not from admin network (flask.json)'],
            }
            return jsonify(json_data), 400


        action = request.json['ACTION_SELECT']
        day_select_str = request.json['DAY_SELECT']

        day_str, night_str = day_select_str.split('_')

        day_date = datetime.strptime(day_str, '%Y-%m-%d').date()

        if night_str == 'night':
            night = True
        else:
            night = False


        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == session['camera_id'])\
            .one()


        if action == 'delete_all':
            video_entry = IndiAllSkyDbVideoTable.query\
                .join(IndiAllSkyDbVideoTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera.id,
                        IndiAllSkyDbVideoTable.dayDate == day_date,
                        IndiAllSkyDbVideoTable.night == night,
                    )
                )\
                .first()

            keogram_entry = IndiAllSkyDbKeogramTable.query\
                .join(IndiAllSkyDbKeogramTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera.id,
                        IndiAllSkyDbKeogramTable.dayDate == day_date,
                        IndiAllSkyDbKeogramTable.night == night,
                    )
                )\
                .first()

            startrail_entry = IndiAllSkyDbStarTrailsTable.query\
                .join(IndiAllSkyDbStarTrailsTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera.id,
                        IndiAllSkyDbStarTrailsTable.dayDate == day_date,
                        IndiAllSkyDbStarTrailsTable.night == night,
                    )
                )\
                .first()

            startrail_video_entry = IndiAllSkyDbStarTrailsVideoTable.query\
                .join(IndiAllSkyDbStarTrailsVideoTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera.id,
                        IndiAllSkyDbStarTrailsVideoTable.dayDate == day_date,
                        IndiAllSkyDbStarTrailsVideoTable.night == night,
                    )
                )\
                .first()


            if video_entry:
                video_entry.deleteAsset()
                db.session.delete(video_entry)

            if keogram_entry:
                keogram_entry.deleteAsset()
                db.session.delete(keogram_entry)

            if startrail_entry:
                startrail_entry.deleteAsset()
                db.session.delete(startrail_entry)

            if startrail_video_entry:
                startrail_video_entry.deleteAsset()
                db.session.delete(startrail_video_entry)


            db.session.commit()


            message = {
                'success-message' : 'Files deleted',
            }

            return jsonify(message)


        elif action == 'delete_video':
            video_entry = IndiAllSkyDbVideoTable.query\
                .join(IndiAllSkyDbVideoTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera.id,
                        IndiAllSkyDbVideoTable.dayDate == day_date,
                        IndiAllSkyDbVideoTable.night == night,
                    )
                )\
                .first()

            if video_entry:
                video_entry.deleteAsset()
                db.session.delete(video_entry)


            db.session.commit()


            message = {
                'success-message' : 'Timelapse deleted',
            }

            return jsonify(message)


        if action == 'delete_k_st':
            keogram_entry = IndiAllSkyDbKeogramTable.query\
                .join(IndiAllSkyDbKeogramTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera.id,
                        IndiAllSkyDbKeogramTable.dayDate == day_date,
                        IndiAllSkyDbKeogramTable.night == night,
                    )
                )\
                .first()

            startrail_entry = IndiAllSkyDbStarTrailsTable.query\
                .join(IndiAllSkyDbStarTrailsTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera.id,
                        IndiAllSkyDbStarTrailsTable.dayDate == day_date,
                        IndiAllSkyDbStarTrailsTable.night == night,
                    )
                )\
                .first()

            startrail_video_entry = IndiAllSkyDbStarTrailsVideoTable.query\
                .join(IndiAllSkyDbStarTrailsVideoTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera.id,
                        IndiAllSkyDbStarTrailsVideoTable.dayDate == day_date,
                        IndiAllSkyDbStarTrailsVideoTable.night == night,
                    )
                )\
                .first()


            if keogram_entry:
                keogram_entry.deleteAsset()
                db.session.delete(keogram_entry)

            if startrail_entry:
                startrail_entry.deleteAsset()
                db.session.delete(startrail_entry)

            if startrail_video_entry:
                startrail_video_entry.deleteAsset()
                db.session.delete(startrail_video_entry)


            db.session.commit()


            message = {
                'success-message' : 'Keogram/Star Trails deleted',
            }

            return jsonify(message)


        elif action == 'generate_all':
            timespec = day_date.strftime('%Y%m%d')

            if night:
                timeofday_str = 'night'
            else:
                timeofday_str = 'day'


            image_dir = Path(self.indi_allsky_config['IMAGE_FOLDER']).absolute()

            img_day_folder = image_dir.joinpath('ccd_{0:s}'.format(camera.uuid), '{0:s}'.format(timespec), timeofday_str)
            if not img_day_folder.exists():
                # try legacy folder
                img_day_folder = image_dir.joinpath('{0:s}'.format(timespec), timeofday_str)


            app.logger.warning('Generating %s time timelapse for %s camera %d', timeofday_str, timespec, camera.id)

            jobdata_video = {
                'action'      : 'generateVideo',
                'timespec'    : timespec,
                'img_folder'  : str(img_day_folder),
                'night'       : night,
                'camera_id'   : camera.id,
            }

            jobdata_kst = {
                'action'      : 'generateKeogramStarTrails',
                'timespec'    : timespec,
                'img_folder'  : str(img_day_folder),
                'night'       : night,
                'camera_id'   : camera.id,
            }


            task_video = IndiAllSkyDbTaskQueueTable(
                queue=TaskQueueQueue.VIDEO,
                state=TaskQueueState.MANUAL,
                data=jobdata_video,
            )
            task_kst = IndiAllSkyDbTaskQueueTable(
                queue=TaskQueueQueue.VIDEO,
                state=TaskQueueState.MANUAL,
                data=jobdata_kst,
            )

            db.session.add(task_video)
            db.session.add(task_kst)

            db.session.commit()

            message = {
                'success-message' : 'Job submitted',
            }

            return jsonify(message)


        elif action == 'generate_video':
            timespec = day_date.strftime('%Y%m%d')

            if night:
                timeofday_str = 'night'
            else:
                timeofday_str = 'day'


            image_dir = Path(self.indi_allsky_config['IMAGE_FOLDER']).absolute()

            img_day_folder = image_dir.joinpath('ccd_{0:s}'.format(camera.uuid), '{0:s}'.format(timespec), timeofday_str)
            if not img_day_folder.exists():
                # try legacy folder
                img_day_folder = image_dir.joinpath('{0:s}'.format(timespec), timeofday_str)


            app.logger.warning('Generating %s time timelapse for %s camera %d', timeofday_str, timespec, camera.id)

            jobdata = {
                'action'      : 'generateVideo',
                'timespec'    : timespec,
                'img_folder'  : str(img_day_folder),
                'night'       : night,
                'camera_id'   : camera.id,
            }

            task = IndiAllSkyDbTaskQueueTable(
                queue=TaskQueueQueue.VIDEO,
                state=TaskQueueState.MANUAL,
                data=jobdata,
            )
            db.session.add(task)
            db.session.commit()

            message = {
                'success-message' : 'Job submitted',
            }

            return jsonify(message)


        elif action == 'generate_k_st':
            timespec = day_date.strftime('%Y%m%d')

            if night:
                timeofday_str = 'night'
            else:
                timeofday_str = 'day'


            image_dir = Path(self.indi_allsky_config['IMAGE_FOLDER']).absolute()

            img_day_folder = image_dir.joinpath('ccd_{0:s}'.format(camera.uuid), '{0:s}'.format(timespec), timeofday_str)
            if not img_day_folder.exists():
                # try legacy folder
                img_day_folder = image_dir.joinpath('{0:s}'.format(timespec), timeofday_str)


            app.logger.warning('Generating %s time timelapse for %s camera %d', timeofday_str, timespec, camera.id)

            jobdata = {
                'action'      : 'generateKeogramStarTrails',
                'timespec'    : timespec,
                'img_folder'  : str(img_day_folder),
                'night'       : night,
                'camera_id'   : camera.id,
            }

            task = IndiAllSkyDbTaskQueueTable(
                queue=TaskQueueQueue.VIDEO,
                state=TaskQueueState.MANUAL,
                data=jobdata,
            )
            db.session.add(task)
            db.session.commit()

            message = {
                'success-message' : 'Job submitted',
            }

            return jsonify(message)

        else:
            # this should never happen
            message = {
                'error-message' : 'Invalid'
            }
            return jsonify(message), 400


class FocusView(TemplateView):
    decorators = [login_required]

    def get_context(self):
        context = super(FocusView, self).get_context()

        context['form_focus'] = IndiAllskyFocusForm()

        return context


class JsonFocusView(JsonView):
    decorators = [login_required]

    def __init__(self, **kwargs):
        super(JsonFocusView, self).__init__(**kwargs)


    def dispatch_request(self):
        zoom = int(request.args.get('zoom', 2))

        json_data = dict()
        json_data['focus_mode'] = self.indi_allsky_config.get('FOCUS_MODE', False)

        image_dir = Path(self.indi_allsky_config['IMAGE_FOLDER']).absolute()
        latest_image_p = image_dir.joinpath('latest.{0:s}'.format(self.indi_allsky_config['IMAGE_FILE_TYPE']))

        image_data = cv2.imread(str(latest_image_p), cv2.IMREAD_UNCHANGED)
        if isinstance(image_data, type(None)):
            app.logger.error('Unable to read %s', latest_image_p)
            return jsonify({}), 400


        image_height, image_width = image_data.shape[:2]

        ### get ROI based on zoom
        x1 = int((image_width / 2) - (image_width / zoom))
        y1 = int((image_height / 2) - (image_height / zoom))
        x2 = int((image_width / 2) + (image_width / zoom))
        y2 = int((image_height / 2) + (image_height / zoom))

        image_roi = image_data[
            y1:y2,
            x1:x2,
        ]


        # returns tuple: rc, data
        json_image_data = cv2.imencode('.jpg', image_roi, [cv2.IMWRITE_JPEG_QUALITY, 75])
        json_image_b64 = base64.b64encode(json_image_data[1])

        json_data['image_b64'] = json_image_b64.decode('utf-8')


        ### Blur detection
        vl_start = time.time()

        ### determine variance of laplacian
        blur_score = cv2.Laplacian(image_roi, cv2.CV_32F).var()
        json_data['blur_score'] = float(blur_score)

        vl_elapsed_s = time.time() - vl_start
        app.logger.info('Variance of laplacien in %0.4f s', vl_elapsed_s)


        return jsonify(json_data)


class LogView(TemplateView):
    decorators = [login_required]

    def get_context(self):
        context = super(LogView, self).get_context()

        context['form_logviewer'] = IndiAllskyLogViewerForm()

        return context


class JsonLogView(JsonView):
    decorators = [login_required]

    def __init__(self, **kwargs):
        super(JsonLogView, self).__init__(**kwargs)


    def dispatch_request(self):
        line_size = 150  # assuming lines have an average length

        lines = int(request.args.get('lines', 500))

        json_data = dict()


        if lines > 5000:
            # sanity check
            lines = 5000


        read_bytes = lines * line_size


        log_file_p = Path('/var/log/indi-allsky/indi-allsky.log')

        log_file_size = log_file_p.stat().st_size
        if log_file_size < read_bytes:
            # just read the whole file
            #app.logger.info('Returning %d bytes of log data', log_file_size)
            log_file_seek = 0
        else:
            #app.logger.info('Returning %d bytes of log data', read_bytes)
            log_file_seek = log_file_size - read_bytes


        log_file_f = io.open(log_file_p, 'r')
        log_file_f.seek(log_file_seek)
        log_lines = log_file_f.readlines()

        log_file_f.close()


        try:
            log_lines.pop(0)  # skip the first partial line
            log_lines.reverse()  # newer lines first
        except IndexError:
            app.logger.warning('indi-allsky log empty')
            log_lines = list()


        json_data['log'] = ''.join(log_lines)

        return jsonify(json_data)


class NotificationsView(TemplateView):
    decorators = [login_required]

    def get_context(self):
        context = super(NotificationsView, self).get_context()


        notices = IndiAllSkyDbNotificationTable.query\
            .order_by(IndiAllSkyDbNotificationTable.createDate.desc())\
            .limit(50)


        notice_list = list()
        for notice in notices:
            n = {
                'id'            : notice.id,
                'createDate'    : notice.createDate,
                'expireDate'    : notice.expireDate,
                'category'      : notice.category.value,
                'ack'           : notice.ack,
                'notification'  : notice.notification,
            }

            notice_list.append(n)

        context['notice_list'] = notice_list

        return context


class AjaxNotificationView(BaseView):
    methods = ['GET', 'POST']
    decorators = []  # manually handle if user is logged in


    def __init__(self, **kwargs):
        super(AjaxNotificationView, self).__init__(**kwargs)


    def dispatch_request(self):
        if not current_user.is_authenticated:
            no_data = {
                'id' : 0,
            }
            return jsonify(no_data)


        if request.method == 'POST':
            return self.post()
        elif request.method == 'GET':
            return self.get()
        else:
            return jsonify({}), 400


    def get(self):
        # return a single result, newest first
        now = datetime.now()

        # this MUST ALWAYS return the newest result
        notice = IndiAllSkyDbNotificationTable.query\
            .filter(
                and_(
                    IndiAllSkyDbNotificationTable.ack == sa_false(),
                    IndiAllSkyDbNotificationTable.expireDate > now,
                )
            )\
            .order_by(IndiAllSkyDbNotificationTable.createDate.desc())\
            .first()


        if not notice:
            no_data = {
                'id' : 0,
            }
            return jsonify(no_data)


        data = {
            'id'            : notice.id,
            'createDate'    : notice.createDate.strftime('%Y-%m-%d %H:%M:%S'),
            'category'      : notice.category.value,
            'notification'  : notice.notification,
        }

        return jsonify(data)


    def post(self):
        ack_id = request.json['ack_id']

        try:
            notice = IndiAllSkyDbNotificationTable.query\
                .filter(IndiAllSkyDbNotificationTable.id == ack_id)\
                .one()

            notice.setAck()
        except NoResultFound:
            pass


        # return next notification
        return self.get()


class UserInfoView(TemplateView):
    decorators = [login_required]

    def get_context(self):
        context = super(UserInfoView, self).get_context()

        form_data = {
            'USERNAME' : current_user.username,
            'NAME'     : current_user.name,
            'EMAIL'    : current_user.email,
            'ADMIN'    : current_user.admin,
        }

        context['form_userinfo'] = IndiAllskyUserInfoForm(data=form_data)

        return context


class AjaxUserInfoView(BaseView):
    methods = ['POST']


    def __init__(self, **kwargs):
        super(AjaxUserInfoView, self).__init__(**kwargs)


    def dispatch_request(self):
        if request.method == 'POST':
            return self.post()
        else:
            return jsonify({}), 400


    def post(self):
        form_userinfo = IndiAllskyUserInfoForm(data=request.json)


        if not form_userinfo.validate(current_user):
            form_errors = form_userinfo.errors  # this must be a property
            form_errors['form_global'] = ['Please fix the errors above']
            return jsonify(form_errors), 400


        # check current password (again)
        current_password = str(request.json['CURRENT_PASSWORD'])
        if not argon2.verify(current_password, current_user.password):
            message = {
                'CURRENT_PASSWORD' : ['Current password is not valid'],
            }
            return jsonify(message), 400


        new_name = str(request.json['NAME'])
        new_password = str(request.json['NEW_PASSWORD'])
        # email is read only
        # admin is read only


        current_user.name = new_name


        if new_password:
            # do not update password if not defined
            hashed_password = argon2.hash(new_password)
            current_user.password = hashed_password
            current_user.passwordDate = datetime.now()


        db.session.commit()


        message = {
            'success-message' : 'User info updated',
        }
        return jsonify(message)


class UsersView(TemplateView):
    decorators = [login_required]

    def get_context(self):
        context = super(UsersView, self).get_context()


        user_list = IndiAllSkyDbUserTable.query\
            .order_by(IndiAllSkyDbUserTable.createDate.asc())

        context['user_list'] = user_list

        return context


class ConfigListView(TemplateView):
    decorators = [login_required]

    def get_context(self):
        context = super(ConfigListView, self).get_context()

        config_list = IndiAllSkyDbConfigTable.query\
            .add_columns(
                IndiAllSkyDbConfigTable.id,
                IndiAllSkyDbConfigTable.createDate,
                IndiAllSkyDbConfigTable.level,
                IndiAllSkyDbConfigTable.note,
                IndiAllSkyDbConfigTable.encrypted,
                IndiAllSkyDbUserTable.username,
            )\
            .join(IndiAllSkyDbUserTable)\
            .order_by(IndiAllSkyDbConfigTable.createDate.desc())\
            .limit(25)

        context['config_list'] = config_list

        return context



class AjaxSelectCameraView(BaseView):
    methods = ['POST']


    def __init__(self, **kwargs):
        super(AjaxSelectCameraView, self).__init__(**kwargs)


    def dispatch_request(self):
        if request.method == 'POST':
            return self.post()
        else:
            return jsonify({}), 400


    def post(self):
        camera_id = int(request.json['camera_id'])

        try:
            camera = IndiAllSkyDbCameraTable.query\
                .filter(IndiAllSkyDbCameraTable.id == camera_id)\
                .one()
        except NoResultFound:
            return jsonify({}), 400


        session['camera_id'] = camera.id


        # return next notification
        return jsonify({})



# images are normally served directly by the web server, this is a backup method
@bp_allsky.route('/images/<path:path>')  # noqa: E302
def images_folder(path):
    app.logger.warning('Serving image file: %s', path)
    return send_from_directory(app.config['INDI_ALLSKY_IMAGE_FOLDER'], path)



bp_allsky.add_url_rule('/', view_func=IndexView.as_view('index_view', template_name='index.html'))
bp_allsky.add_url_rule('/js/latest', view_func=JsonLatestImageView.as_view('js_latest_image_view'))
bp_allsky.add_url_rule('/imageviewer', view_func=ImageViewerView.as_view('imageviewer_view', template_name='imageviewer.html'))
bp_allsky.add_url_rule('/videoviewer', view_func=VideoViewerView.as_view('videoviewer_view', template_name='videoviewer.html'))
bp_allsky.add_url_rule('/config', view_func=ConfigView.as_view('config_view', template_name='config.html'))
bp_allsky.add_url_rule('/sqm', view_func=SqmView.as_view('sqm_view', template_name='sqm.html'))
bp_allsky.add_url_rule('/loop', view_func=ImageLoopView.as_view('image_loop_view', template_name='loop.html'))
bp_allsky.add_url_rule('/js/loop', view_func=JsonImageLoopView.as_view('js_image_loop_view'))
bp_allsky.add_url_rule('/charts', view_func=ChartView.as_view('chart_view', template_name='chart.html'))
bp_allsky.add_url_rule('/js/charts', view_func=JsonChartView.as_view('js_chart_view'))
bp_allsky.add_url_rule('/system', view_func=SystemInfoView.as_view('system_view', template_name='system.html'))
bp_allsky.add_url_rule('/timelapse', view_func=TimelapseGeneratorView.as_view('timelapse_view', template_name='timelapse.html'))
bp_allsky.add_url_rule('/focus', view_func=FocusView.as_view('focus_view', template_name='focus.html'))
bp_allsky.add_url_rule('/js/focus', view_func=JsonFocusView.as_view('js_focus_view'))
bp_allsky.add_url_rule('/log', view_func=LogView.as_view('log_view', template_name='log.html'))
bp_allsky.add_url_rule('/js/log', view_func=JsonLogView.as_view('js_log_view'))
bp_allsky.add_url_rule('/user', view_func=UserInfoView.as_view('user_view', template_name='user.html'))
bp_allsky.add_url_rule('/ajax/user', view_func=AjaxUserInfoView.as_view('ajax_user_view'))

bp_allsky.add_url_rule('/public', view_func=PublicIndexView.as_view('public_index_view'))  # redirect

bp_allsky.add_url_rule('/ajax/imageviewer', view_func=AjaxImageViewerView.as_view('ajax_imageviewer_view'))
bp_allsky.add_url_rule('/ajax/videoviewer', view_func=AjaxVideoViewerView.as_view('ajax_videoviewer_view'))
bp_allsky.add_url_rule('/ajax/config', view_func=AjaxConfigView.as_view('ajax_config_view'))
bp_allsky.add_url_rule('/ajax/system', view_func=AjaxSystemInfoView.as_view('ajax_system_view'))
bp_allsky.add_url_rule('/ajax/settime', view_func=AjaxSetTimeView.as_view('ajax_settime_view'))
bp_allsky.add_url_rule('/ajax/timelapse', view_func=AjaxTimelapseGeneratorView.as_view('ajax_timelapse_view'))
bp_allsky.add_url_rule('/ajax/notification', view_func=AjaxNotificationView.as_view('ajax_notification_view'))
bp_allsky.add_url_rule('/ajax/selectcamera', view_func=AjaxSelectCameraView.as_view('ajax_select_camera_view'))

# hidden
bp_allsky.add_url_rule('/cameras', view_func=CamerasView.as_view('cameras_view', template_name='cameras.html'))
bp_allsky.add_url_rule('/darks', view_func=DarkFramesView.as_view('darks_view', template_name='darks.html'))
bp_allsky.add_url_rule('/tasks', view_func=TaskQueueView.as_view('taskqueue_view', template_name='taskqueue.html'))
bp_allsky.add_url_rule('/lag', view_func=ImageLagView.as_view('image_lag_view', template_name='lag.html'))
bp_allsky.add_url_rule('/adu', view_func=RollingAduView.as_view('rolling_adu_view', template_name='adu.html'))
bp_allsky.add_url_rule('/notifications', view_func=NotificationsView.as_view('notifications_view', template_name='notifications.html'))
bp_allsky.add_url_rule('/users', view_func=UsersView.as_view('users_view', template_name='users.html'))
bp_allsky.add_url_rule('/configlist', view_func=ConfigListView.as_view('configlist_view', template_name='configlist.html'))

