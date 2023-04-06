
# S3 assets
ASSET_IMAGE     = 1
ASSET_TIMELAPSE = 2


# Types
CAMERA          = 1
IMAGE           = 2
VIDEO           = 3
KEOGRAM         = 4
STARTRAIL       = 5
STARTRAIL_VIDEO = 6
RAW_IMAGE       = 7
FITS_IMAGE      = 8
USER            = 9
DARK_FRAME      = 10
BPM_FRAME       = 11


ENDPOINT_V1 = {
    CAMERA          : 'sync/v1/camera',
    IMAGE           : 'sync/v1/image',
    VIDEO           : 'sync/v1/video',
    KEOGRAM         : 'sync/v1/keogram',
    STARTRAIL       : 'sync/v1/startrail',
    STARTRAIL_VIDEO : 'sync/v1/startrailvideo',
    RAW_IMAGE       : 'sync/v1/rawimage',
    FITS_IMAGE      : 'sync/v1/fitsimage',
    #USER            : 'sync/v1/user',
}


# File transfers
TRANSFER_UPLOAD  = 1
TRANSFER_MQTT    = 2
TRANSFER_S3      = 3
TRANSFER_SYNC_V1 = 4


# CFA Types
CFA_RGGB = 46  # cv2.COLOR_BAYER_BG2BGR
CFA_GRBG = 47  # cv2.COLOR_BAYER_GB2BGR
CFA_BGGR = 48  # cv2.COLOR_BAYER_RG2BGR
CFA_GBRG = 49  # cv2.COLOR_BAYER_GR2BGR

CFA_STR_MAP = {
    'RGGB' : CFA_RGGB,
    'GRBG' : CFA_GRBG,
    'BGGR' : CFA_BGGR,
    'GBRG' : CFA_GBRG,
    None   : None
}

CFA_MAP_STR = {
    CFA_RGGB : 'RGGB',
    CFA_GRBG : 'GRBG',
    CFA_BGGR : 'BGGR',
    CFA_GBRG : 'GBRG',
}

