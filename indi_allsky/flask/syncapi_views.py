import time
from datetime import datetime
from datetime import timedelta
from pathlib import Path
import hashlib
import json
import tempfile
import shutil


from flask import request
from flask import Blueprint
from flask import jsonify
from flask import abort
from flask import current_app as app

#from flask_login import login_required

#from .. import constants

from .base_views import BaseView

from . import db

from .models import IndiAllSkyDbCameraTable
from .models import IndiAllSkyDbImageTable
from .models import IndiAllSkyDbVideoTable
from .models import IndiAllSkyDbKeogramTable
from .models import IndiAllSkyDbStarTrailsTable
from .models import IndiAllSkyDbStarTrailsVideoTable
from .models import IndiAllSkyDbRawImageTable
from .models import IndiAllSkyDbFitsImageTable
from .models import IndiAllSkyDbUserTable

from sqlalchemy.orm.exc import NoResultFound


bp_syncapi_allsky = Blueprint(
    'syncapi_indi_allsky',
    __name__,
    #url_prefix='/',  # wsgi
    url_prefix='/indi-allsky',  # gunicorn
)


class SyncApiBaseView(BaseView):
    decorators = []

    model = None
    filename_t = None
    add_function = None


    def __init__(self, **kwargs):
        super(SyncApiBaseView, self).__init__(**kwargs)

        if self.indi_allsky_config.get('IMAGE_FOLDER'):
            self.image_dir = Path(self.indi_allsky_config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.parent.joinpath('html', 'images').absolute()


    def dispatch_request(self):
        self.authorize()

        # we are now authenticated

        if request.method == 'POST':
            return self.post()
        elif request.method == 'PUT':
            return self.put()
        elif request.method == 'DELETE':
            return self.delete()
        elif request.method == 'GET':
            return self.get()
        else:
            return jsonify({}), 400


    def post(self, overwrite=False):
        metadata = self.saveMetadata()
        media_file = self.saveFile()

        camera = self.getCamera(metadata)


        try:
            file_entry = self.processPost(camera, metadata, media_file, overwrite=overwrite)
        except EntryExists:
            return jsonify({'error' : 'file_exists'}), 400


        return jsonify({
            'id'   : file_entry.id,
            'url'  : str(file_entry.getUrl(local=True)),
        })


    def put(self, overwrite=True):
        return self.post(overwrite=overwrite)


    def delete(self):
        metadata = self.saveMetadata()
        # no media
        # no camera

        try:
            self.deleteFile(metadata['id'])
        except EntryMissing:
            return jsonify({'error' : 'file_missing'}), 400

        return jsonify({})


    def get(self):
        get_id = request.args.get('id')

        try:
            file_entry = self.getEntry(get_id)
        except EntryMissing:
            return jsonify({'error' : 'file_missing'}), 400

        return jsonify({
            'id'   : file_entry.id,
            'url'  : str(file_entry.getUrl(local=True)),
        })


    def processPost(self, camera, metadata, tmp_file, overwrite=False):
        d_dayDate = datetime.strptime(metadata['dayDate'], '%Y%m%d').date()

        date_folder = self.image_dir.joinpath('ccd_{0:s}'.format(camera.uuid), d_dayDate.strftime('%Y%m%d'))
        if not date_folder.exists():
            date_folder.mkdir(mode=0o755)


        if metadata['night']:
            timeofday_str = 'night'
        else:
            timeofday_str = 'day'

        filename = date_folder.joinpath(self.filename_t.format(camera.id, d_dayDate.strftime('%Y%m%d'), timeofday_str, tmp_file.suffix))

        if not filename.exists():
            try:
                # delete old entry if it exists
                old_entry = self.model.query\
                    .filter(self.model.filename == str(filename))\
                    .one()

                app.logger.warning('Removing orphaned video entry')
                db.session.delete(old_entry)
                db.session.commit()
            except NoResultFound:
                pass

        else:
            if not overwrite:
                raise EntryExists()

            app.logger.warning('Replacing file')
            filename.unlink()

            try:
                old_entry = self.model.query\
                    .filter(self.model.filename == str(filename))\
                    .one()

                app.logger.warning('Removing old entry')
                db.session.delete(old_entry)
                db.session.commit()
            except NoResultFound:
                pass


        # do not sync these metadata keys for now
        exclude_keys = []
        for k in exclude_keys:
            try:
                metadata.pop(k)
            except KeyError:
                pass


        addFunction_method = getattr(self._miscDb, self.add_function)
        new_entry = addFunction_method(
            filename,
            camera.id,
            metadata,
        )

        shutil.copy2(str(tmp_file), str(filename))
        filename.chmod(0o644)

        tmp_file.unlink()

        app.logger.info('Uploaded file: %s', filename)

        return new_entry


    def deleteFile(self, entry_id):
        # we do not want to call deleteAsset() here
        try:
            entry = self.model.query\
                .filter(self.model.id == entry_id)\
                .one()


            entry.deleteFile()

            app.logger.warning('Deleting entry %d', entry.id)
            db.session.delete(entry)
            db.session.commit()
        except NoResultFound:
            raise EntryMissing()


    def getEntry(self, entry_id):
        try:
            entry = self.model.query\
                .filter(self.model.id == entry_id)\
                .one()

        except NoResultFound:
            raise EntryMissing()


        return entry


    def saveMetadata(self):
        metadata_file = request.files['metadata']
        metadata_json = json.load(metadata_file)

        #app.logger.info('Json: %s', metadata_json)

        return metadata_json


    def saveFile(self):
        media_file = request.files['media']

        media_file_p = Path(media_file.filename)  # need this for the extension

        f_tmp_media = tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix=media_file_p.suffix)
        while True:
            data = media_file.read(32768)
            if data:
                f_tmp_media.write(data)
            else:
                break

        f_tmp_media.close()

        #app.logger.info('File: %s', media_file_p)

        return Path(f_tmp_media.name)



    #def put(self):
    #    #media_file = request.files.get('media')
    #    pass


    def authorize(self):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            app.logger.error('Missing Authoriation header')
            return abort(400)

        try:
            bearer, user_apikey_hash = auth_header.split(' ')
        except ValueError:
            app.logger.error('Malformed API key')
            return abort(400)


        try:
            username, apikey_hash = user_apikey_hash.split(':')
        except ValueError:
            app.logger.error('Malformed API key')
            return abort(400)


        user = IndiAllSkyDbUserTable.query\
            .filter(IndiAllSkyDbUserTable.username == username)\
            .first()


        if not user:
            app.logger.error('Unknown user')
            return abort(400)


        apikey = user.getApiKey(app.config['PASSWORD_KEY'])


        time_floor = int(time.time() / 300) * 300

        # the time on the remote system needs to be plus/minus the time_floor period
        time_floor_list = [time_floor, time_floor - 1, time_floor + 1]
        for t in time_floor_list:
            api_hash = hashlib.sha256('{0:d}{1:s}'.format(t, apikey).encode()).hexdigest()
            if apikey_hash == api_hash:
                break
        else:
            app.logger.error('Unable to authenticate API key')
            return abort(400)


    def getCamera(self, metadata):
        # not catching NoResultFound
        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.uuid == metadata['camera_uuid'])\
            .one()

        return camera


class SyncApiCameraView(SyncApiBaseView):
    decorators = []

    model = IndiAllSkyDbCameraTable
    filename_t = None
    add_function = 'addCamera_remote'


    def get(self):
        get_id = request.args.get('id')

        try:
            file_entry = self.getEntry(get_id)
        except EntryMissing:
            return jsonify({'error' : 'camera_missing'}), 400

        return jsonify({
            'id'   : file_entry.id,
        })


    def post(self, overwrite=True):
        metadata = self.saveMetadata()


        camera_entry = self.processPost(None, metadata, None, overwrite=overwrite)

        return jsonify({
            'id'   : camera_entry.id,
        })


    def put(self, overwrite=True):
        return self.post(overwrite=overwrite)


    def processPost(self, notUsed1, metadata, notUsed2, overwrite=True):
        addFunction_method = getattr(self._miscDb, self.add_function)
        entry = addFunction_method(
            metadata,
        )

        app.logger.info('Updated camera: %s', entry.uuid)

        return entry


    def delete(self):
        return jsonify({'error' : 'not_implemented'}), 400


class SyncApiImageView(SyncApiBaseView):
    decorators = []

    model = IndiAllSkyDbImageTable
    filename_t = 'ccd{0:d}_{1:s}{2:s}'  # no dot for extension
    add_function = 'addImage'


    def processPost(self, camera, image_metadata, tmp_file, overwrite=False):
        createDate = datetime.fromtimestamp(image_metadata['createDate'])
        folder = self.getImageFolder(createDate, image_metadata['night'], camera)

        date_str = createDate.strftime('%Y%m%d_%H%M%S')
        image_file = folder.joinpath(self.filename_t.format(camera.id, date_str, tmp_file.suffix))  # suffix includes dot


        if not image_file.exists():
            try:
                # delete old entry if it exists
                old_image_entry = self.model.query\
                    .filter(self.model.filename == str(image_file))\
                    .one()

                app.logger.warning('Removing orphaned image entry')
                db.session.delete(old_image_entry)
                db.session.commit()
            except NoResultFound:
                pass


        else:
            if not overwrite:
                raise EntryExists()

            app.logger.warning('Replacing image')
            image_file.unlink()

            try:
                old_image_entry = self.model.query\
                    .filter(self.model.filename == str(image_file))\
                    .one()

                app.logger.warning('Removing old image entry')
                db.session.delete(old_image_entry)
                db.session.commit()
            except NoResultFound:
                pass


        addFunction_method = getattr(self._miscDb, self.add_function)
        new_entry = addFunction_method(
            image_file,
            camera.id,
            image_metadata,
        )

        shutil.copy2(str(tmp_file), str(image_file))
        image_file.chmod(0o644)

        tmp_file.unlink()

        app.logger.info('Uploaded image: %s', image_file)

        return new_entry


    def getImageFolder(self, exp_date, night, camera):
        if night:
            # images should be written to previous day's folder until noon
            day_ref = exp_date - timedelta(hours=12)
            timeofday_str = 'night'
        else:
            # images should be written to current day's folder
            day_ref = exp_date
            timeofday_str = 'day'

        hour_str = exp_date.strftime('%d_%H')

        day_folder = self.image_dir.joinpath('ccd_{0:s}'.format(camera.uuid), '{0:s}'.format(day_ref.strftime('%Y%m%d')), timeofday_str)

        if not day_folder.exists():
            day_folder.mkdir(mode=0o755, parents=True)

        hour_folder = day_folder.joinpath('{0:s}'.format(hour_str))
        if not hour_folder.exists():
            hour_folder.mkdir(mode=0o755)

        return hour_folder


class SyncApiVideoView(SyncApiBaseView):
    decorators = []

    model = IndiAllSkyDbVideoTable
    filename_t = 'allsky-timelapse_ccd{0:d}_{1:s}_{2:s}{3:s}'
    add_function = 'addVideo'


class SyncApiKeogramView(SyncApiBaseView):
    decorators = []

    model = IndiAllSkyDbKeogramTable
    filename_t = 'allsky-keogram_ccd{0:d}_{1:s}_{2:s}{3:s}'
    add_function = 'addKeogram'


class SyncApiStartrailView(SyncApiBaseView):
    decorators = []

    model = IndiAllSkyDbStarTrailsTable
    filename_t = 'allsky-startrail_ccd{0:d}_{1:s}_{2:s}{3:s}'
    add_function = 'addStarTrail'


class SyncApiStartrailVideoView(SyncApiBaseView):
    decorators = []

    model = IndiAllSkyDbStarTrailsVideoTable
    filename_t = 'allsky-startrail_timelapse_ccd{0:d}_{1:s}_{2:s}{3:s}'
    add_function = 'addStarTrailVideo'


class SyncApiRawImageView(SyncApiImageView):  # image parent
    decorators = []

    model = IndiAllSkyDbRawImageTable
    filename_t = 'ccd{0:d}_{1:s}{2:s}'
    add_function = 'addRawImage'

    # fixme need processImage/getImageFolder function for export folder


class SyncApiFitsImageView(SyncApiImageView):  # image parent
    decorators = []

    model = IndiAllSkyDbFitsImageTable
    filename_t = 'ccd{0:d}_{1:s}{2:s}'
    add_function = 'addFitsImage'


class EntryExists(Exception):
    pass


class EntryMissing(Exception):
    pass


bp_syncapi_allsky.add_url_rule('/sync/v1/camera', view_func=SyncApiCameraView.as_view('syncapi_v1_camera_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])
bp_syncapi_allsky.add_url_rule('/sync/v1/image', view_func=SyncApiImageView.as_view('syncapi_v1_image_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])
bp_syncapi_allsky.add_url_rule('/sync/v1/video', view_func=SyncApiVideoView.as_view('syncapi_v1_video_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])
bp_syncapi_allsky.add_url_rule('/sync/v1/keogram', view_func=SyncApiKeogramView.as_view('syncapi_v1_keogram_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])
bp_syncapi_allsky.add_url_rule('/sync/v1/startrail', view_func=SyncApiStartrailView.as_view('syncapi_v1_startrail_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])
bp_syncapi_allsky.add_url_rule('/sync/v1/startrailvideo', view_func=SyncApiStartrailVideoView.as_view('syncapi_v1_startrail_video_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])
bp_syncapi_allsky.add_url_rule('/sync/v1/rawimage', view_func=SyncApiRawImageView.as_view('syncapi_v1_rawimage_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])
bp_syncapi_allsky.add_url_rule('/sync/v1/fitsimage', view_func=SyncApiFitsImageView.as_view('syncapi_v1_fitsimage_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])

