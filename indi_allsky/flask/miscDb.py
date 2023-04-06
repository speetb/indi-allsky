from datetime import datetime
from datetime import timedelta
from pathlib import Path
import uuid
import logging
#from pprint import pformat

from . import db

from .models import IndiAllSkyDbCameraTable
from .models import IndiAllSkyDbImageTable
from .models import IndiAllSkyDbBadPixelMapTable
from .models import IndiAllSkyDbDarkFrameTable
from .models import IndiAllSkyDbVideoTable
from .models import IndiAllSkyDbKeogramTable
from .models import IndiAllSkyDbStarTrailsTable
from .models import IndiAllSkyDbStarTrailsVideoTable
from .models import IndiAllSkyDbFitsImageTable
from .models import IndiAllSkyDbRawImageTable
from .models import IndiAllSkyDbNotificationTable
from .models import IndiAllSkyDbStateTable

#from .models import NotificationCategory

from sqlalchemy.orm.exc import NoResultFound

logger = logging.getLogger('indi_allsky')


class miscDb(object):
    def __init__(self, config):
        self.config = config


    def addCamera(self, metadata):
        now = datetime.now()

        try:
            camera = IndiAllSkyDbCameraTable.query\
                .filter(IndiAllSkyDbCameraTable.name == metadata['name'])\
                .one()
            camera.connectDate = now

            if not camera.uuid:
                camera.uuid = str(uuid.uuid4())
        except NoResultFound:
            camera = IndiAllSkyDbCameraTable(
                name=metadata['name'],
                connectDate=now,
                local=True,
                uuid=str(uuid.uuid4()),
            )

            db.session.add(camera)
            db.session.commit()


        keys_exclude = [
            'id',
            'name',
            'uuid',
            'type',
            'local',
            'filename',
            's3_key',
            'remote_url',
            #'sync_id',
            #'friendlyName',
        ]

        # populate camera info
        for k, v in metadata.items():
            if k in keys_exclude:
                continue

            setattr(camera, k, v)


        db.session.commit()

        logger.info('Camera DB ID: %d', camera.id)

        return camera


    def addCamera_remote(self, metadata):
        now = datetime.now()

        try:
            camera = IndiAllSkyDbCameraTable.query\
                .filter(IndiAllSkyDbCameraTable.uuid == metadata['uuid'])\
                .one()

            camera.connectDate = now
        except NoResultFound:
            camera = IndiAllSkyDbCameraTable(
                name=metadata['uuid'],  # use uuid initially for uniqueness
                connectDate=now,
                local=False,
                uuid=metadata['uuid']
            )

            db.session.add(camera)
            db.session.commit()


        # The camera name and friendlyName must be unique
        camera.name = '{0:s} {1:d}'.format(metadata['name'], camera.id)

        if metadata.get('friendlyName'):
            camera.friendlyName = '{0:s} {1:d}'.format(metadata['friendlyName'], camera.id)


        keys_exclude = [
            'id',
            'name',
            'uuid',
            'type',
            'local',
            'sync_id',
            'friendlyName',
            'filename',
            's3_key',
            'remote_url',
        ]

        # populate camera info
        for k, v in metadata.items():
            if k in keys_exclude:
                continue

            setattr(camera, k, v)


        db.session.commit()

        logger.info('Camera DB ID: %d', camera.id)

        return camera


    def addImage(self, filename, camera_id, metadata):

        ### expected metadata
        #{
        #    'createDate'  # datetime or timestamp
        #    'exposure'
        #    'exp_elapsed'
        #    'gain'
        #    'binmode'
        #    'temp'
        #    'adu'
        #    'stable'
        #    'moonmode'
        #    'moonphase'
        #    'night'
        #    'sqm'
        #    'adu_roi'
        #    'calibrated'
        #    'stars'
        #    'detections'
        #    'process_elapsed'
        #}

        if not filename:
            return

        filename_p = Path(filename)  # file might not exist when entry created


        logger.info('Adding image %s to DB', filename_p)

        if isinstance(metadata['createDate'], (int, float)):
            createDate = datetime.fromtimestamp(metadata['createDate'])
        else:
            createDate = metadata['createDate']


        if metadata['night']:
            # day date for night is offset by 12 hours
            dayDate = (createDate - timedelta(hours=12)).date()
        else:
            dayDate = createDate.date()


        # If temp is 0, write null
        if metadata['temp']:
            temp_val = float(metadata['temp'])
        else:
            temp_val = None


        # if moonmode is 0, moonphase is Null
        if metadata['moonmode']:
            moonphase_val = float(metadata['moonmode'])
        else:
            moonphase_val = None

        moonmode_val = bool(metadata['moonmode'])

        night_val = bool(metadata['night'])  # integer to boolean
        adu_roi_val = bool(metadata['adu_roi'])


        image = IndiAllSkyDbImageTable(
            camera_id=camera_id,
            filename=str(filename_p),
            createDate=createDate,
            dayDate=dayDate,
            exposure=metadata['exposure'],
            exp_elapsed=metadata['exp_elapsed'],
            gain=metadata['gain'],
            binmode=metadata['binmode'],
            temp=temp_val,
            calibrated=metadata['calibrated'],
            night=night_val,
            adu=metadata['adu'],
            adu_roi=adu_roi_val,
            stable=metadata['stable'],
            moonmode=moonmode_val,
            moonphase=moonphase_val,
            sqm=metadata['sqm'],
            stars=metadata['stars'],
            detections=metadata['detections'],
            process_elapsed=metadata['process_elapsed'],
            remote_url=metadata.get('remote_url'),
            s3_key=metadata.get('s3_key'),
        )

        db.session.add(image)
        db.session.commit()

        return image


    def addDarkFrame(self, filename, camera_id, metadata):

        ### expected metadata
        #{
        #    'createDate'  # datetime or timestamp
        #    'bitdepth'
        #    'exposure'
        #    'gain'
        #    'binmode'
        #    'temp'
        #}


        if not filename:
            return

        filename_p = Path(filename)


        logger.info('Adding dark frame %s to DB', filename_p)


        if isinstance(metadata['createDate'], (int, float)):
            createDate = datetime.fromtimestamp(metadata['createDate'])
        else:
            createDate = metadata['createDate']


        exposure_int = int(metadata['exposure'])


        # If temp is 0, write null
        if metadata['temp']:
            temp_val = float(metadata['temp'])
        else:
            logger.warning('Temperature is not defined')
            temp_val = None


        dark = IndiAllSkyDbDarkFrameTable(
            createDate=createDate,
            camera_id=camera_id,
            filename=str(filename_p),
            bitdepth=metadata['bitdepth'],
            exposure=exposure_int,
            gain=metadata['gain'],
            binmode=metadata['binmode'],
            temp=temp_val,
        )

        db.session.add(dark)
        db.session.commit()

        return dark


    def addBadPixelMap(self, filename, camera_id, metadata):

        ### expected metadata
        #{
        #    'createDate'  # datetime or timestamp
        #    'bitdepth'
        #    'exposure'
        #    'gain'
        #    'binmode'
        #    'temp'
        #}


        if not filename:
            return

        filename_p = Path(filename)


        logger.info('Adding bad pixel map %s to DB', filename_p)

        if isinstance(metadata['createDate'], (int, float)):
            createDate = datetime.fromtimestamp(metadata['createDate'])
        else:
            createDate = metadata['createDate']


        exposure_int = int(metadata['exposure'])


        # If temp is 0, write null
        if metadata['temp']:
            temp_val = float(metadata['temp'])
        else:
            logger.warning('Temperature is not defined')
            temp_val = None


        bpm = IndiAllSkyDbBadPixelMapTable(
            createDate=createDate,
            camera_id=camera_id,
            filename=str(filename_p),
            bitdepth=metadata['bitdepth'],
            exposure=exposure_int,
            gain=metadata['gain'],
            binmode=metadata['binmode'],
            temp=temp_val,
        )

        db.session.add(bpm)
        db.session.commit()

        return bpm


    def addVideo(self, filename, camera_id, metadata):

        ### expected metadata
        #{
        #    'createDate'  # datetime or timestamp
        #    'dayDate'  # date or string
        #    'night'
        #}


        if not filename:
            return

        filename_p = Path(filename)


        logger.info('Adding video %s to DB', filename_p)

        if isinstance(metadata['createDate'], (int, float)):
            createDate = datetime.fromtimestamp(metadata['createDate'])
        else:
            createDate = metadata['createDate']


        if isinstance(metadata['dayDate'], str):
            dayDate = datetime.strptime(metadata['dayDate'], '%Y%m%d').date()
        else:
            dayDate = metadata['dayDate']



        video = IndiAllSkyDbVideoTable(
            createDate=createDate,
            camera_id=camera_id,
            filename=str(filename_p),
            dayDate=dayDate,
            night=metadata['night'],
            remote_url=metadata.get('remote_url'),
            s3_key=metadata.get('s3_key'),
        )

        db.session.add(video)
        db.session.commit()

        return video


    def addKeogram(self, filename, camera_id, metadata):

        ### expected metadata
        #{
        #    'createDate'  # datetime or timestamp
        #    'dayDate'  # date or string
        #    'night'
        #}

        if not filename:
            return

        filename_p = Path(filename)


        logger.info('Adding keogram %s to DB', filename_p)


        if isinstance(metadata['createDate'], (int, float)):
            createDate = datetime.fromtimestamp(metadata['createDate'])
        else:
            createDate = metadata['createDate']


        if isinstance(metadata['dayDate'], str):
            dayDate = datetime.strptime(metadata['dayDate'], '%Y%m%d').date()
        else:
            dayDate = metadata['dayDate']



        keogram = IndiAllSkyDbKeogramTable(
            createDate=createDate,
            camera_id=camera_id,
            filename=str(filename_p),
            dayDate=dayDate,
            night=metadata['night'],
            remote_url=metadata.get('remote_url'),
            s3_key=metadata.get('s3_key'),
        )

        db.session.add(keogram)
        db.session.commit()

        return keogram


    def addStarTrail(self, filename, camera_id, metadata):

        ### expected metadata
        #{
        #    'createDate'  # datetime or timestamp
        #    'dayDate'  # date or string
        #    'night'
        #}


        if not filename:
            return

        filename_p = Path(filename)


        logger.info('Adding star trail %s to DB', filename_p)


        if isinstance(metadata['createDate'], (int, float)):
            createDate = datetime.fromtimestamp(metadata['createDate'])
        else:
            createDate = metadata['createDate']


        if isinstance(metadata['dayDate'], str):
            dayDate = datetime.strptime(metadata['dayDate'], '%Y%m%d').date()
        else:
            dayDate = metadata['dayDate']



        startrail = IndiAllSkyDbStarTrailsTable(
            createDate=createDate,
            camera_id=camera_id,
            filename=str(filename_p),
            dayDate=dayDate,
            night=metadata['night'],
            remote_url=metadata.get('remote_url'),
            s3_key=metadata.get('s3_key'),
        )

        db.session.add(startrail)
        db.session.commit()

        return startrail


    def addStarTrailVideo(self, filename, camera_id, metadata):

        ### expected metadata
        #{
        #    'createDate'  # datetime or timestamp
        #    'dayDate'  # date or string
        #    'night'
        #}


        if not filename:
            return

        filename_p = Path(filename)


        logger.info('Adding star trail video %s to DB', filename_p)


        if isinstance(metadata['createDate'], (int, float)):
            createDate = datetime.fromtimestamp(metadata['createDate'])
        else:
            createDate = metadata['createDate']


        if isinstance(metadata['dayDate'], str):
            dayDate = datetime.strptime(metadata['dayDate'], '%Y%m%d').date()
        else:
            dayDate = metadata['dayDate']



        startrail_video = IndiAllSkyDbStarTrailsVideoTable(
            createDate=createDate,
            camera_id=camera_id,
            filename=str(filename_p),
            dayDate=dayDate,
            night=metadata['night'],
            remote_url=metadata.get('remote_url'),
            s3_key=metadata.get('s3_key'),
        )

        db.session.add(startrail_video)
        db.session.commit()

        return startrail_video


    def addFitsImage(self, filename, camera_id, metadata):

        ### expected metadata
        #{
        #    'createDate'  # datetime or timestamp
        #    'exposure'
        #    'gain'
        #    'binmode'
        #    'night'
        #}

        if not filename:
            return

        filename_p = Path(filename)


        if isinstance(metadata['createDate'], (int, float)):
            createDate = datetime.fromtimestamp(metadata['createDate'])
        else:
            createDate = metadata['createDate']


        if metadata['night']:
            # day date for night is offset by 12 hours
            dayDate = (createDate - timedelta(hours=12)).date()
        else:
            dayDate = createDate.date()


        logger.info('Adding fits image %s to DB', filename_p)


        fits_image = IndiAllSkyDbFitsImageTable(
            camera_id=camera_id,
            filename=str(filename_p),
            createDate=createDate,
            exposure=metadata['exposure'],
            gain=metadata['gain'],
            binmode=metadata['binmode'],
            dayDate=dayDate,
            night=metadata['night'],
            remote_url=metadata.get('remote_url'),
            s3_key=metadata.get('s3_key'),
        )

        db.session.add(fits_image)
        db.session.commit()

        return fits_image


    def addRawImage(self, filename, camera_id, metadata):

        ### expected metadata
        #{
        #    'createDate'  # datetime or timestamp
        #    'exposure'
        #    'gain'
        #    'binmode'
        #    'night'
        #}

        if not filename:
            return

        filename_p = Path(filename)


        if isinstance(metadata['createDate'], (int, float)):
            createDate = datetime.fromtimestamp(metadata['createDate'])
        else:
            createDate = metadata['createDate']


        if metadata['night']:
            # day date for night is offset by 12 hours
            dayDate = (createDate - timedelta(hours=12)).date()
        else:
            dayDate = createDate.date()


        logger.info('Adding raw image %s to DB', filename_p)


        raw_image = IndiAllSkyDbRawImageTable(
            camera_id=camera_id,
            filename=str(filename_p),
            createDate=createDate,
            exposure=metadata['exposure'],
            gain=metadata['gain'],
            binmode=metadata['binmode'],
            dayDate=dayDate,
            night=metadata['night'],
            remote_url=metadata.get('remote_url'),
            s3_key=metadata.get('s3_key'),
        )

        db.session.add(raw_image)
        db.session.commit()

        return raw_image


    def getCurrentCameraId(self):
        try:
            camera_id = int(self.getState('DB_CAMERA_ID'))
            return camera_id
        except NoResultFound:
            pass

        try:
            camera = IndiAllSkyDbCameraTable.query\
                .order_by(IndiAllSkyDbCameraTable.connectDate.desc())\
                .limit(1)\
                .one()
            return camera.id
        except NoResultFound:
            logger.error('No cameras found')
            raise


    def addNotification(self, category, item, notification, expire=timedelta(hours=12)):
        now = datetime.now()

        # look for existing notification
        notice = IndiAllSkyDbNotificationTable.query\
            .filter(IndiAllSkyDbNotificationTable.item == item)\
            .filter(IndiAllSkyDbNotificationTable.category == category)\
            .filter(IndiAllSkyDbNotificationTable.expireDate > now)\
            .first()

        if notice:
            logger.warning('Not adding existing notification')
            return


        new_notice = IndiAllSkyDbNotificationTable(
            item=item,
            category=category,
            notification=notification,
            expireDate=now + expire,
        )

        db.session.add(new_notice)
        db.session.commit()

        logger.info('Added %s notification: %d', category.value, new_notice.id)

        return new_notice


    def setState(self, key, value):
        now = datetime.now()

        # all keys must be upper-case
        key_upper = str(key).upper()

        # all values must be strings
        value_str = str(value)

        try:
            state = IndiAllSkyDbStateTable.query\
                .filter(IndiAllSkyDbStateTable.key == key_upper)\
                .one()

            state.value = value_str
            state.createDate = now
        except NoResultFound:
            state = IndiAllSkyDbStateTable(
                key=key_upper,
                value=value_str,
                createDate=now,
            )

            db.session.add(state)


        db.session.commit()


    def getState(self, key):
        # all values must be upper-case strings
        key_upper = str(key).upper()

        # not catching NoResultFound
        state = IndiAllSkyDbStateTable.query\
            .filter(IndiAllSkyDbStateTable.key == key_upper)\
            .one()

        return state.value


