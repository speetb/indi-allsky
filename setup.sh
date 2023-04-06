#!/bin/bash

#set -x  # command tracing
#set -o errexit  # replace by trapping ERR
#set -o nounset  # problems with python virtualenvs
shopt -s nullglob

PATH=/usr/bin:/bin
export PATH


### Non-interactive options example ###
#export INDIALLSKY_CAMERA_INTERFACE=indi
#export INDIALLSKY_INSTALL_INDI=true
#export INDIALLSKY_INSTALL_LIBCAMERA=false
#export INDIALLSKY_INSTALL_INDISERVER=true
#export INDIALLSKY_HTTP_PORT=80
#export INDIALLSKY_HTTPS_PORT=443
#export INDIALLSKY_TIMEZONE="America/New_York"
#export INDIALLSKY_INDI_VERSION=1.9.9
#export INDIALLSKY_CCD_DRIVER=indi_simulator_ccd
#export INDIALLSKY_GPS_DRIVER=None
#export INDIALLSKY_FLASK_AUTH_ALL_VIEWS=true
#export INDIALLSKY_WEB_USER=user@example.org
#export INDIALLSKY_WEB_PASS=password
#export INDIALLSKY_WEB_NAME="First Last"
#export INDIALLSKY_WEB_EMAIL=user@example.org
###


#### config ####
INDI_DRIVER_PATH="/usr/bin"

INDISERVER_SERVICE_NAME="indiserver"
ALLSKY_SERVICE_NAME="indi-allsky"
GUNICORN_SERVICE_NAME="gunicorn-indi-allsky"

ALLSKY_ETC="/etc/indi-allsky"
DOCROOT_FOLDER="/var/www/html"
HTDOCS_FOLDER="${DOCROOT_FOLDER}/allsky"

DB_FOLDER="/var/lib/indi-allsky"
DB_FILE="${DB_FOLDER}/indi-allsky.sqlite"
SQLALCHEMY_DATABASE_URI="sqlite:///${DB_FILE}"
MIGRATION_FOLDER="$DB_FOLDER/migrations"

# mysql support is not ready
USE_MYSQL_DATABASE="${INDIALLSKY_USE_MYSQL_DATABASE:-false}"

CAMERA_INTERFACE="${INDIALLSKY_CAMERA_INTERFACE:-}"
DPC_STRENGTH="0"

INSTALL_INDI="${INDIALLSKY_INSTALL_INDI:-true}"
INSTALL_LIBCAMERA="${INDIALLSKY_INSTALL_LIBCAMERA:-false}"

INSTALL_INDISERVER="${INDIALLSKY_INSTALL_INDISERVER:-}"
INDI_VERSION="${INDIALLSKY_INDI_VERSION:-}"

CCD_DRIVER="${INDIALLSKY_CCD_DRIVER:-}"
GPS_DRIVER="${INDIALLSKY_GPS_DRIVER:-}"

HTTP_PORT="${INDIALLSKY_HTTP_PORT:-80}"
HTTPS_PORT="${INDIALLSKY_HTTPS_PORT:-443}"

FLASK_AUTH_ALL_VIEWS="${INDIALLSKY_FLASK_AUTH_ALL_VIEWS:-}"
WEB_USER="${INDIALLSKY_WEB_USER:-}"
WEB_PASS="${INDIALLSKY_WEB_PASS:-}"
WEB_NAME="${INDIALLSKY_WEB_NAME:-}"
WEB_EMAIL="${INDIALLSKY_WEB_EMAIL:-}"

PYINDI_1_9_9="git+https://github.com/indilib/pyindi-client.git@ce808b7#egg=pyindi-client"
PYINDI_1_9_8="git+https://github.com/indilib/pyindi-client.git@ffd939b#egg=pyindi-client"
#### end config ####


### libcamera Defective Pixel Correction (DPC) Strength
# https://datasheets.raspberrypi.com/camera/raspberry-pi-camera-guide.pdf
#
# 0 = Off
# 1 = Normal correction (default)
# 2 = Strong correction
###


function catch_error() {
    echo
    echo
    echo "The script exited abnormally, please try to run again..."
    echo
    echo
    exit 1
}
trap catch_error ERR

function catch_sigint() {
    echo
    echo
    echo "The setup script was interrupted, please run the script again to finish..."
    echo
    echo
    exit 1
}
trap catch_sigint SIGINT



HTDOCS_FILES="
    .htaccess
"

IMAGE_FOLDER_FILES="
    .htaccess
    darks/.htaccess
    export/.htaccess
"


DISTRO_NAME=$(lsb_release -s -i)
DISTRO_RELEASE=$(lsb_release -s -r)
CPU_ARCH=$(uname -m)

# get primary group
PGRP=$(id -ng)


echo "###############################################"
echo "### Welcome to the indi-allsky setup script ###"
echo "###############################################"


if [ -f "/usr/local/bin/indiserver" ]; then
    # Do not install INDI
    INSTALL_INDI="false"
    INDI_DRIVER_PATH="/usr/local/bin"

    echo
    echo
    echo "Detected a custom installation of INDI in /usr/local/bin"
    echo
    echo
    sleep 3
fi


if [[ -f "/etc/astroberry.version" ]]; then
    ASTROBERRY="true"
    echo
    echo
    echo "Detected Astroberry server"
    echo

    # Astroberry already has services on 80/443
    if [ "$HTTP_PORT" -eq 80 ]; then
        HTTP_PORT="81"
        echo "Changing HTTP_PORT to 81"
    fi

    if [ "$HTTPS_PORT" -eq 443 ]; then
        HTTPS_PORT="444"
        echo "Changing HTTPS_PORT to 444"
    fi

    echo
    echo
    sleep 3
else
    ASTROBERRY="false"
fi


if systemctl --user -q is-active indi-allsky >/dev/null 2>&1; then
    echo
    echo
    echo "WARNING: indi-allsky is running.  It is recommended to stop the service before running this script."
    echo
    sleep 5
fi


echo
echo
echo "Distribution: $DISTRO_NAME"
echo "Release: $DISTRO_RELEASE"
echo "Arch: $CPU_ARCH"
echo
echo "INDI_DRIVER_PATH: $INDI_DRIVER_PATH"
echo "INDISERVER_SERVICE_NAME: $INDISERVER_SERVICE_NAME"
echo "ALLSKY_SERVICE_NAME: $ALLSKY_SERVICE_NAME"
echo "GUNICORN_SERVICE_NAME: $GUNICORN_SERVICE_NAME"
echo "ALLSKY_ETC: $ALLSKY_ETC"
echo "HTDOCS_FOLDER: $HTDOCS_FOLDER"
echo "DB_FOLDER: $DB_FOLDER"
echo "DB_FILE: $DB_FILE"
echo "INSTALL_INDI: $INSTALL_INDI"
echo "HTTP_PORT: $HTTP_PORT"
echo "HTTPS_PORT: $HTTPS_PORT"
echo
echo

if [[ "$(id -u)" == "0" ]]; then
    echo "Please do not run $(basename "$0") as root"
    echo "Re-run this script as the user which will execute the indi-allsky software"
    echo
    echo
    exit 1
fi

if [[ -n "$VIRTUAL_ENV" ]]; then
    echo "Please do not run $(basename "$0") with a virtualenv active"
    echo "Run \"deactivate\" to exit your current virtualenv"
    echo
    echo
    exit 1
fi

if ! ping -c 1 "$(hostname -s)" >/dev/null 2>&1; then
    echo "To avoid the benign warnings 'Name or service not known sudo: unable to resolve host'"
    echo "Add the following line to your /etc/hosts file:"
    echo "127.0.0.1       localhost $(hostname -s)"
    echo
    echo
fi

echo "Setup proceeding in 10 seconds... (control-c to cancel)"
echo
sleep 10


# Run sudo to ask for initial password
sudo true


START_TIME=$(date +%s)


echo
echo
echo "indi-allsky supports the following camera interfaces."
echo
echo "indi: For astro/planetary cameras normally connected via USB"
echo "libcamera: supports cameras connected via CSI interface on Raspberry Pi SoCs"
echo

# whiptail might not be installed yet
while [ -z "${CAMERA_INTERFACE:-}" ]; do
    PS3="Select a camera interface: "
    select camera_interface in indi libcamera; do
        if [ -n "$camera_interface" ]; then
            CAMERA_INTERFACE=$camera_interface
            break
        fi
    done


    # more specific libcamera selection
    if [ "$CAMERA_INTERFACE" == "libcamera" ]; then
        echo
        PS3="Select a libcamera interface: "
        select libcamera_interface in libcamera_imx477 libcamera_imx378 libcamera_imx519 libcamera_imx708 libcamera_imx290 libcamera_imx462 libcamera_64mp_hawkeye; do
            if [ -n "$libcamera_interface" ]; then
                # overwrite variable
                CAMERA_INTERFACE=$libcamera_interface
                break
            fi
        done
    fi
done


if [[ "$CAMERA_INTERFACE" =~ "^libcamera" ]]; then
    INSTALL_LIBCAMERA="true"
fi


echo
echo
echo "Fixing git checkout permissions"
sudo find "$(dirname "$0")" ! -user "$USER" -exec chown "$USER" {} \;
sudo find "$(dirname "$0")" -type d ! -perm -555 -exec chmod ugo+rx {} \;
sudo find "$(dirname "$0")" -type f ! -perm -444 -exec chmod ugo+r {} \;



echo "**** Installing packages... ****"
if [[ "$DISTRO_NAME" == "Raspbian" && "$DISTRO_RELEASE" == "11" ]]; then
    DEBIAN_DISTRO=1
    REDHAT_DISTRO=0

    RSYSLOG_USER=root
    RSYSLOG_GROUP=adm

    MYSQL_ETC="/etc/mysql"

    PYTHON_BIN=python3

    if [ "$CPU_ARCH" == "armv7l" ]; then
        # rawpy not available on 32bit
        VIRTUALENV_REQ=requirements_debian11_32.txt
    elif [ "$CPU_ARCH" == "i686" ]; then
        VIRTUALENV_REQ=requirements_debian11_32.txt
    else
        VIRTUALENV_REQ=requirements_debian11.txt
    fi


    # reconfigure system timezone
    if [ -n "${INDIALLSKY_TIMEZONE:-}" ]; then
        # this is not validated
        echo
        echo "Setting timezone to $INDIALLSKY_TIMEZONE"
        echo "$INDIALLSKY_TIMEZONE" | sudo tee /etc/timezone
        sudo dpkg-reconfigure -f noninteractive tzdata
    else
        sudo dpkg-reconfigure tzdata
    fi


    if [[ "$CPU_ARCH" == "aarch64" ]]; then
        # Astroberry repository
        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" && ! -f "/etc/apt/sources.list.d/astroberry.list" ]]; then
            echo "Installing INDI via Astroberry repository"
            wget -O - https://www.astroberry.io/repo/key | sudo apt-key add -
            echo "deb https://www.astroberry.io/repo/ bullseye main" | sudo tee /etc/apt/sources.list.d/astroberry.list
        fi
    else
        INSTALL_INDI="false"

        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
            echo
            echo
            echo "There are not prebuilt indi packages for this distribution"
            echo "Please run ./misc/build_indi.sh before running setup.sh"
            echo
            echo
            exit 1
        fi
    fi


    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        virtualenv \
        cmake \
        gfortran \
        whiptail \
        rsyslog \
        cron \
        git \
        cpio \
        tzdata \
        ca-certificates \
        avahi-daemon \
        apache2 \
        libgnutls28-dev \
        swig \
        libatlas-base-dev \
        libilmbase-dev \
        libopenexr-dev \
        libgtk-3-0 \
        libssl-dev \
        libxml2-dev \
        libxslt-dev \
        libgnutls28-dev \
        libcurl4-gnutls-dev \
        libcfitsio-dev \
        libnova-dev \
        libdbus-1-dev \
        libglib2.0-dev \
        libffi-dev \
        libopencv-dev \
        libopenblas-dev \
        default-libmysqlclient-dev \
        pkg-config \
        rustc \
        cargo \
        ffmpeg \
        gifsicle \
        jq \
        sqlite3 \
        policykit-1 \
        dbus-user-session


    if [[ "$USE_MYSQL_DATABASE" == "true" ]]; then
        sudo apt-get -y install \
            mariadb-server
    fi


    if [[ "$INSTALL_INDI" == "true" && -f "/usr/bin/indiserver" ]]; then
        if ! whiptail --title "indi software update" --yesno "INDI is already installed, would you like to upgrade the software?" 0 0 --defaultno; then
            INSTALL_INDI="false"
        fi
    fi

    if [[ "$INSTALL_INDI" == "true" ]]; then
        sudo apt-get -y install \
            indi-full \
            libindi-dev \
            indi-webcam \
            indi-asi \
            libasi \
            indi-qhy \
            libqhy \
            indi-playerone \
            libplayerone \
            indi-sv305 \
            libsv305 \
            libaltaircam \
            libmallincam \
            libmicam \
            libnncam \
            indi-toupbase \
            libtoupcam \
            indi-gphoto \
            indi-sx
    fi

    if [[ "$INSTALL_LIBCAMERA" == "true" ]]; then
        sudo apt-get -y install \
            libcamera-apps
    fi


elif [[ "$DISTRO_NAME" == "Raspbian" && "$DISTRO_RELEASE" == "10" ]]; then
    DEBIAN_DISTRO=1
    REDHAT_DISTRO=0

    RSYSLOG_USER=root
    RSYSLOG_GROUP=adm

    MYSQL_ETC="/etc/mysql"

    PYTHON_BIN=python3

    VIRTUALENV_REQ=requirements_debian10.txt


    if [[ "$CAMERA_INTERFACE" =~ "^libcamera" ]]; then
        echo
        echo
        echo "libcamera is not supported in this distribution"
        exit 1
    fi


    # reconfigure system timezone
    if [ -n "${INDIALLSKY_TIMEZONE:-}" ]; then
        # this is not validated
        echo
        echo "Setting timezone to $INDIALLSKY_TIMEZONE"
        echo "$INDIALLSKY_TIMEZONE" | sudo tee /etc/timezone
        sudo dpkg-reconfigure -f noninteractive tzdata
    else
        sudo dpkg-reconfigure tzdata
    fi


    if [[ "$CPU_ARCH" == "armv7l" || "$CPU_ARCH" == "armv6l" ]]; then
        # Astroberry repository
        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" && ! -f "/etc/apt/sources.list.d/astroberry.list" ]]; then
            echo "Installing INDI via Astroberry repository"
            wget -O - https://www.astroberry.io/repo/key | sudo apt-key add -
            echo "deb https://www.astroberry.io/repo/ buster main" | sudo tee /etc/apt/sources.list.d/astroberry.list
        fi
    fi


    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        virtualenv \
        cmake \
        gfortran \
        whiptail \
        rsyslog \
        cron \
        git \
        cpio \
        tzdata \
        ca-certificates \
        avahi-daemon \
        apache2 \
        swig \
        libatlas-base-dev \
        libilmbase-dev \
        libopenexr-dev \
        libgtk-3-0 \
        libssl-dev \
        libxml2-dev \
        libxslt-dev \
        libgnutls28-dev \
        libcurl4-gnutls-dev \
        libcfitsio-dev \
        libnova-dev \
        libdbus-1-dev \
        libglib2.0-dev \
        libffi-dev \
        libopencv-dev \
        libopenblas-dev \
        default-libmysqlclient-dev \
        pkg-config \
        rustc \
        cargo \
        ffmpeg \
        gifsicle \
        jq \
        sqlite3 \
        policykit-1 \
        dbus-user-session


    if [[ "$USE_MYSQL_DATABASE" == "true" ]]; then
        sudo apt-get -y install \
            mariadb-server
    fi


    if [[ "$INSTALL_INDI" == "true" && -f "/usr/bin/indiserver" ]]; then
        if ! whiptail --title "indi software update" --yesno "INDI is already installed, would you like to upgrade the software?" 0 0 --defaultno; then
            INSTALL_INDI="false"
        fi
    fi

    if [[ "$INSTALL_INDI" == "true" ]]; then
        sudo apt-get -y install \
            indi-full \
            indi-rpicam \
            libindi-dev \
            indi-asi \
            libasi \
            indi-qhy \
            libqhy \
            indi-playerone \
            libplayerone \
            indi-sv305 \
            libsv305 \
            libaltaircam \
            libmallincam \
            libmicam \
            libnncam \
            indi-toupbase \
            libtoupcam \
            indi-gphoto \
            indi-sx
    fi

    if [[ "$INSTALL_LIBCAMERA" == "true" ]]; then
        sudo apt-get -y install \
            libcamera-apps
    fi

elif [[ "$DISTRO_NAME" == "Debian" && "$DISTRO_RELEASE" == "11" ]]; then
    DEBIAN_DISTRO=1
    REDHAT_DISTRO=0

    RSYSLOG_USER=root
    RSYSLOG_GROUP=adm

    MYSQL_ETC="/etc/mysql"

    PYTHON_BIN=python3

    if [ "$CPU_ARCH" == "armv7l" ]; then
        # rawpy not available on 32bit
        VIRTUALENV_REQ=requirements_debian11_32.txt
    elif [ "$CPU_ARCH" == "i686" ]; then
        VIRTUALENV_REQ=requirements_debian11_32.txt
    else
        VIRTUALENV_REQ=requirements_debian11.txt
    fi


    # reconfigure system timezone
    if [ -n "${INDIALLSKY_TIMEZONE:-}" ]; then
        # this is not validated
        echo
        echo "Setting timezone to $INDIALLSKY_TIMEZONE"
        echo "$INDIALLSKY_TIMEZONE" | sudo tee /etc/timezone
        sudo dpkg-reconfigure -f noninteractive tzdata
    else
        sudo dpkg-reconfigure tzdata
    fi


    # Sometimes raspbian can be detected as debian
    if [[ "$CPU_ARCH" == "aarch64" ]]; then
        # Astroberry repository
        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" && ! -f "/etc/apt/sources.list.d/astroberry.list" ]]; then
            echo "Installing INDI via Astroberry repository"
            wget -O - https://www.astroberry.io/repo/key | sudo apt-key add -
            echo "deb https://www.astroberry.io/repo/ bullseye main" | sudo tee /etc/apt/sources.list.d/astroberry.list
        fi
    else
        INSTALL_INDI="false"

        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
            echo
            echo
            echo "There are not prebuilt indi packages for this distribution"
            echo "Please run ./misc/build_indi.sh before running setup.sh"
            echo
            echo
            exit 1
        fi
    fi


    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        virtualenv \
        cmake \
        gfortran \
        whiptail \
        rsyslog \
        cron \
        git \
        cpio \
        tzdata \
        ca-certificates \
        avahi-daemon \
        apache2 \
        libgnutls28-dev \
        swig \
        libatlas-base-dev \
        libilmbase-dev \
        libopenexr-dev \
        libgtk-3-0 \
        libssl-dev \
        libxml2-dev \
        libxslt-dev \
        libgnutls28-dev \
        libcurl4-gnutls-dev \
        libcfitsio-dev \
        libnova-dev \
        libdbus-1-dev \
        libglib2.0-dev \
        libffi-dev \
        libopencv-dev \
        libopenblas-dev \
        default-libmysqlclient-dev \
        pkg-config \
        rustc \
        cargo \
        ffmpeg \
        gifsicle \
        jq \
        sqlite3 \
        policykit-1 \
        dbus-user-session


    if [[ "$USE_MYSQL_DATABASE" == "true" ]]; then
        sudo apt-get -y install \
            mariadb-server
    fi


    if [[ "$INSTALL_INDI" == "true" && -f "/usr/bin/indiserver" ]]; then
        if ! whiptail --title "indi software update" --yesno "INDI is already installed, would you like to upgrade the software?" 0 0 --defaultno; then
            INSTALL_INDI="false"
        fi
    fi

    if [[ "$INSTALL_INDI" == "true" ]]; then
        sudo apt-get -y install \
            indi-full \
            libindi-dev \
            indi-webcam \
            indi-asi \
            libasi \
            indi-qhy \
            libqhy \
            indi-playerone \
            libplayerone \
            indi-sv305 \
            libsv305 \
            libaltaircam \
            libmallincam \
            libmicam \
            libnncam \
            indi-toupbase \
            libtoupcam \
            indi-gphoto \
            indi-sx
    fi


    if [[ "$INSTALL_LIBCAMERA" == "true" ]]; then
        # this can fail on armbian debian based repos
        sudo apt-get -y install \
            libcamera-apps || true
    fi


elif [[ "$DISTRO_NAME" == "Debian" && "$DISTRO_RELEASE" == "10" ]]; then
    DEBIAN_DISTRO=1
    REDHAT_DISTRO=0

    RSYSLOG_USER=root
    RSYSLOG_GROUP=adm

    MYSQL_ETC="/etc/mysql"

    PYTHON_BIN=python3

    VIRTUALENV_REQ=requirements_debian10.txt


    if [[ "$CAMERA_INTERFACE" =~ "^libcamera" ]]; then
        echo
        echo
        echo "libcamera is not supported in this distribution"
        exit 1
    fi


    # Sometimes raspbian can be detected as debian
    if [[ "$CPU_ARCH" == "armv7l" || "$CPU_ARCH" == "armv6l" ]]; then
        # Astroberry repository
        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" && ! -f "/etc/apt/sources.list.d/astroberry.list" ]]; then
            echo "Installing INDI via Astroberry repository"
            wget -O - https://www.astroberry.io/repo/key | sudo apt-key add -
            echo "deb https://www.astroberry.io/repo/ buster main" | sudo tee /etc/apt/sources.list.d/astroberry.list
        fi
    else
        INSTALL_INDI="false"

        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
            echo
            echo
            echo "There are not prebuilt indi packages for this distribution"
            echo "Please run ./misc/build_indi.sh before running setup.sh"
            echo
            echo
            exit 1
        fi
    fi


    # reconfigure system timezone
    if [ -n "${INDIALLSKY_TIMEZONE:-}" ]; then
        # this is not validated
        echo
        echo "Setting timezone to $INDIALLSKY_TIMEZONE"
        echo "$INDIALLSKY_TIMEZONE" | sudo tee /etc/timezone
        sudo dpkg-reconfigure -f noninteractive tzdata
    else
        sudo dpkg-reconfigure tzdata
    fi


    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        virtualenv \
        cmake \
        gfortran \
        whiptail \
        rsyslog \
        cron \
        git \
        cpio \
        tzdata \
        ca-certificates \
        avahi-daemon \
        apache2 \
        swig \
        libatlas-base-dev \
        libilmbase-dev \
        libopenexr-dev \
        libgtk-3-0 \
        libssl-dev \
        libxml2-dev \
        libxslt-dev \
        libgnutls28-dev \
        libcurl4-gnutls-dev \
        libcfitsio-dev \
        libnova-dev \
        libdbus-1-dev \
        libglib2.0-dev \
        libffi-dev \
        libopencv-dev \
        libopenblas-dev \
        default-libmysqlclient-dev \
        pkg-config \
        rustc \
        cargo \
        ffmpeg \
        gifsicle \
        jq \
        sqlite3 \
        policykit-1 \
        dbus-user-session


    if [[ "$USE_MYSQL_DATABASE" == "true" ]]; then
        sudo apt-get -y install \
            mariadb-server
    fi


    if [[ "$INSTALL_INDI" == "true" && -f "/usr/bin/indiserver" ]]; then
        if ! whiptail --title "indi software update" --yesno "INDI is already installed, would you like to upgrade the software?" 0 0 --defaultno; then
            INSTALL_INDI="false"
        fi
    fi

    if [[ "$INSTALL_INDI" == "true" ]]; then
        sudo apt-get -y install \
            indi-full \
            libindi-dev \
            indi-rpicam \
            indi-webcam \
            indi-asi \
            libasi \
            indi-qhy \
            libqhy \
            indi-playerone \
            libplayerone \
            indi-sv305 \
            libsv305 \
            libaltaircam \
            libmallincam \
            libmicam \
            libnncam \
            indi-toupbase \
            libtoupcam \
            indi-gphoto \
            indi-sx
    fi

elif [[ "$DISTRO_NAME" == "Ubuntu" && "$DISTRO_RELEASE" == "22.04" ]]; then
    DEBIAN_DISTRO=1
    REDHAT_DISTRO=0

    RSYSLOG_USER=syslog
    RSYSLOG_GROUP=adm

    MYSQL_ETC="/etc/mysql"

    PYTHON_BIN=python3

    if [ "$CPU_ARCH" == "armv7l" ]; then
        # rawpy not available on 32bit
        VIRTUALENV_REQ=requirements_debian11_32.txt
    elif [ "$CPU_ARCH" == "i686" ]; then
        VIRTUALENV_REQ=requirements_debian11_32.txt
    else
        VIRTUALENV_REQ=requirements_debian11.txt
    fi


    if [[ "$CAMERA_INTERFACE" =~ "^libcamera" ]]; then
        echo
        echo
        echo "libcamera is not supported in this distribution"
        exit 1
    fi


    if [[ "$CPU_ARCH" == "x86_64" ]]; then
        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
            sudo add-apt-repository ppa:mutlaqja/ppa
        fi
    elif [[ "$CPU_ARCH" == "aarch64" || "$CPU_ARCH" == "armv7l" || "$CPU_ARCH" == "armv6l" ]]; then
        INSTALL_INDI="false"

        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
            echo
            echo
            echo "There are not prebuilt indi packages for this distribution"
            echo "Please run ./misc/build_indi.sh before running setup.sh"
            echo
            echo
            exit 1
        fi
    fi


    # reconfigure system timezone
    if [ -n "${INDIALLSKY_TIMEZONE:-}" ]; then
        # this is not validated
        echo
        echo "Setting timezone to $INDIALLSKY_TIMEZONE"
        echo "$INDIALLSKY_TIMEZONE" | sudo tee /etc/timezone
        sudo dpkg-reconfigure -f noninteractive tzdata
    else
        sudo dpkg-reconfigure tzdata
    fi


    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        virtualenv \
        cmake \
        gfortran \
        whiptail \
        rsyslog \
        cron \
        git \
        cpio \
        tzdata \
        ca-certificates \
        avahi-daemon \
        apache2 \
        libgnutls28-dev \
        swig \
        libatlas-base-dev \
        libilmbase-dev \
        libopenexr-dev \
        libgtk-3-0 \
        libssl-dev \
        libxml2-dev \
        libxslt-dev \
        libgnutls28-dev \
        libcurl4-gnutls-dev \
        libcfitsio-dev \
        libnova-dev \
        libdbus-1-dev \
        libglib2.0-dev \
        libffi-dev \
        libopencv-dev \
        libopenblas-dev \
        default-libmysqlclient-dev \
        pkg-config \
        rustc \
        cargo \
        ffmpeg \
        gifsicle \
        jq \
        sqlite3 \
        policykit-1 \
        dbus-user-session


    if [[ "$USE_MYSQL_DATABASE" == "true" ]]; then
        sudo apt-get -y install \
            mariadb-server
    fi


    if [[ "$INSTALL_INDI" == "true" && -f "/usr/bin/indiserver" ]]; then
        if ! whiptail --title "indi software update" --yesno "INDI is already installed, would you like to upgrade the software?" 0 0 --defaultno; then
            INSTALL_INDI="false"
        fi
    fi

    if [[ "$INSTALL_INDI" == "true" ]]; then
        sudo apt-get -y install \
            indi-full \
            libindi-dev \
            indi-webcam \
            indi-asi \
            libasi \
            indi-qhy \
            libqhy \
            indi-playerone \
            libplayerone \
            indi-svbony \
            libsvbony \
            libaltaircam \
            libmallincam \
            libmicam \
            libnncam \
            indi-toupbase \
            libtoupcam \
            indi-gphoto \
            indi-sx
    fi


elif [[ "$DISTRO_NAME" == "Ubuntu" && "$DISTRO_RELEASE" == "20.04" ]]; then
    DEBIAN_DISTRO=1
    REDHAT_DISTRO=0

    RSYSLOG_USER=syslog
    RSYSLOG_GROUP=adm

    MYSQL_ETC="/etc/mysql"

    PYTHON_BIN=python3.9

    if [ "$CPU_ARCH" == "armv7l" ]; then
        # rawpy not available on 32bit
        VIRTUALENV_REQ=requirements_debian11_32.txt
    elif [ "$CPU_ARCH" == "i686" ]; then
        VIRTUALENV_REQ=requirements_debian11_32.txt
    else
        VIRTUALENV_REQ=requirements_debian11.txt
    fi


    if [[ "$CAMERA_INTERFACE" =~ "^libcamera" ]]; then
        echo
        echo
        echo "libcamera is not supported in this distribution"
        exit 1
    fi


    if [[ "$CPU_ARCH" == "x86_64" ]]; then
        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
            sudo add-apt-repository ppa:mutlaqja/ppa
        fi
    elif [[ "$CPU_ARCH" == "aarch64" || "$CPU_ARCH" == "armv7l" || "$CPU_ARCH" == "armv6l" ]]; then
        INSTALL_INDI="false"

        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
            echo
            echo
            echo "There are not prebuilt indi packages for this distribution"
            echo "Please run ./misc/build_indi.sh before running setup.sh"
            echo
            echo
            exit 1
        fi
    fi


    # reconfigure system timezone
    if [ -n "${INDIALLSKY_TIMEZONE:-}" ]; then
        # this is not validated
        echo
        echo "Setting timezone to $INDIALLSKY_TIMEZONE"
        echo "$INDIALLSKY_TIMEZONE" | sudo tee /etc/timezone
        sudo dpkg-reconfigure -f noninteractive tzdata
    else
        sudo dpkg-reconfigure tzdata
    fi


    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        python3.9 \
        python3.9-dev \
        python3.9-venv \
        python3-pip \
        virtualenv \
        cmake \
        gfortran \
        whiptail \
        rsyslog \
        cron \
        git \
        cpio \
        tzdata \
        ca-certificates \
        avahi-daemon \
        apache2 \
        libgnutls28-dev \
        swig \
        libatlas-base-dev \
        libilmbase-dev \
        libopenexr-dev \
        libgtk-3-0 \
        libssl-dev \
        libxml2-dev \
        libxslt-dev \
        libgnutls28-dev \
        libcurl4-gnutls-dev \
        libcfitsio-dev \
        libnova-dev \
        libdbus-1-dev \
        libglib2.0-dev \
        libffi-dev \
        libopencv-dev \
        libopenblas-dev \
        default-libmysqlclient-dev \
        pkg-config \
        rustc \
        cargo \
        ffmpeg \
        gifsicle \
        jq \
        sqlite3 \
        policykit-1 \
        dbus-user-session


    if [[ "$USE_MYSQL_DATABASE" == "true" ]]; then
        sudo apt-get -y install \
            mariadb-server
    fi


    if [[ "$INSTALL_INDI" == "true" && -f "/usr/bin/indiserver" ]]; then
        if ! whiptail --title "indi software update" --yesno "INDI is already installed, would you like to upgrade the software?" 0 0 --defaultno; then
            INSTALL_INDI="false"
        fi
    fi

    if [[ "$INSTALL_INDI" == "true" ]]; then
        sudo apt-get -y install \
            indi-full \
            libindi-dev \
            indi-webcam \
            indi-asi \
            libasi \
            indi-qhy \
            libqhy \
            indi-playerone \
            libplayerone \
            indi-svbony \
            libsvbony \
            libaltaircam \
            libmallincam \
            libmicam \
            libnncam \
            indi-toupbase \
            libtoupcam \
            indi-gphoto \
            indi-sx
    fi

elif [[ "$DISTRO_NAME" == "Ubuntu" && "$DISTRO_RELEASE" == "18.04" ]]; then
    DEBIAN_DISTRO=1
    REDHAT_DISTRO=0

    RSYSLOG_USER=syslog
    RSYSLOG_GROUP=adm

    MYSQL_ETC="/etc/mysql"

    PYTHON_BIN=python3.8

    if [ "$CPU_ARCH" == "armv7l" ]; then
        # rawpy not available on 32bit
        VIRTUALENV_REQ=requirements_debian11_32.txt
    elif [ "$CPU_ARCH" == "i686" ]; then
        VIRTUALENV_REQ=requirements_debian11_32.txt
    else
        VIRTUALENV_REQ=requirements_debian11.txt
    fi



    if [[ "$CAMERA_INTERFACE" =~ "^libcamera" ]]; then
        echo
        echo
        echo "libcamera is not supported in this distribution"
        exit 1
    fi


    # reconfigure system timezone
    if [ -n "${INDIALLSKY_TIMEZONE:-}" ]; then
        # this is not validated
        echo
        echo "Setting timezone to $INDIALLSKY_TIMEZONE"
        echo "$INDIALLSKY_TIMEZONE" | sudo tee /etc/timezone
        sudo dpkg-reconfigure -f noninteractive tzdata
    else
        sudo dpkg-reconfigure tzdata
    fi


    if [[ "$CPU_ARCH" == "x86_64" ]]; then
        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
            sudo add-apt-repository ppa:mutlaqja/ppa
        fi
    fi


    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        python3.8 \
        python3.8-dev \
        python3.8-venv \
        python3-pip \
        virtualenv \
        cmake \
        gfortran \
        whiptail \
        rsyslog \
        cron \
        git \
        cpio \
        tzdata \
        ca-certificates \
        avahi-daemon \
        apache2 \
        swig \
        libatlas-base-dev \
        libilmbase-dev \
        libopenexr-dev \
        libgtk-3-0 \
        libssl-dev \
        libxml2-dev \
        libxslt-dev \
        libgnutls28-dev \
        libcurl4-gnutls-dev \
        libcfitsio-dev \
        libnova-dev \
        zlib1g-dev \
        libgnutls28-dev \
        libdbus-1-dev \
        libglib2.0-dev \
        libffi-dev \
        libopencv-dev \
        libopenblas-dev \
        default-libmysqlclient-dev \
        pkg-config \
        rustc \
        cargo \
        ffmpeg \
        gifsicle \
        jq \
        sqlite3 \
        policykit-1 \
        dbus-user-session


    if [[ "$USE_MYSQL_DATABASE" == "true" ]]; then
        sudo apt-get -y install \
            mariadb-server
    fi


    if [[ "$INSTALL_INDI" == "true" && -f "/usr/bin/indiserver" ]]; then
        if ! whiptail --title "indi software update" --yesno "INDI is already installed, would you like to upgrade the software?" 0 0 --defaultno; then
            INSTALL_INDI="false"
        fi
    fi

    if [[ "$INSTALL_INDI" == "true" ]]; then
        sudo apt-get -y install \
            indi-full \
            libindi-dev \
            indi-webcam \
            indi-asi \
            libasi \
            indi-qhy \
            libqhy \
            indi-playerone \
            libplayerone \
            libaltaircam \
            libmallincam \
            libmicam \
            libnncam \
            indi-toupbase \
            libtoupcam \
            indi-gphoto \
            indi-sx

            # no packages for 18.04
            #indi-sv305 \
            #libsv305 \
    fi

else
    echo "Unknown distribution $DISTRO_NAME $DISTRO_RELEASE ($CPU_ARCH)"
    exit 1
fi


if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
    echo
    echo
    echo "The DBUS user session is not defined"
    echo
    echo "Now that the dbus package has been installed..."
    echo "Please reboot your system and re-run this script to continue"
    echo
    exit 1
fi


if systemctl -q is-enabled "${INDISERVER_SERVICE_NAME}" 2>/dev/null; then
    # system
    INSTALL_INDISERVER="false"
elif systemctl --user -q is-enabled "${INDISERVER_SERVICE_NAME}" 2>/dev/null; then
    while [ -z "${INSTALL_INDISERVER:-}" ]; do
        # user
        if whiptail --title "indiserver update" --yesno "An indiserver service is already defined, would you like to replace it?" 0 0 --defaultno; then
            INSTALL_INDISERVER="true"
        else
            INSTALL_INDISERVER="false"
        fi
    done
else
    INSTALL_INDISERVER="true"
fi


# find script directory for service setup
SCRIPT_DIR=$(dirname "$0")
cd "$SCRIPT_DIR" || catch_error
ALLSKY_DIRECTORY=$PWD
cd "$OLDPWD" || catch_error


echo "**** Ensure path to git folder is traversable ****"
# Web servers running as www-data or nobody need to be able to read files in the git checkout
PARENT_DIR="$ALLSKY_DIRECTORY"
while true; do
    if [ "$PARENT_DIR" == "/" ]; then
        break
    elif [ "$PARENT_DIR" == "." ]; then
        break
    fi

    echo "Setting other execute bit on $PARENT_DIR"
    sudo chmod ugo+x "$PARENT_DIR"

    PARENT_DIR=$(dirname "$PARENT_DIR")
done


echo "**** Python virtualenv setup ****"
[[ ! -d "${ALLSKY_DIRECTORY}/virtualenv" ]] && mkdir "${ALLSKY_DIRECTORY}/virtualenv"
chmod 775 "${ALLSKY_DIRECTORY}/virtualenv"
if [ ! -d "${ALLSKY_DIRECTORY}/virtualenv/indi-allsky" ]; then
    virtualenv -p "${PYTHON_BIN}" "${ALLSKY_DIRECTORY}/virtualenv/indi-allsky"
fi
# shellcheck source=/dev/null
source "${ALLSKY_DIRECTORY}/virtualenv/indi-allsky/bin/activate"
pip3 install --upgrade pip setuptools wheel
pip3 install -r "${ALLSKY_DIRECTORY}/${VIRTUALENV_REQ}"



# pyindi-client setup
SUPPORTED_INDI_VERSIONS=(
    "2.0.0"
    "1.9.9"
    "1.9.8"
    "1.9.7"
    "skip"
)


# try to detect installed indiversion
#DETECTED_INDIVERSION=$(${INDI_DRIVER_PATH}/indiserver --help 2>&1 | grep -i "INDI Library" | awk "{print \$3}")
DETECTED_INDIVERSION=$(pkg-config --modversion libindi)
echo
echo
echo "Detected INDI version: $DETECTED_INDIVERSION"
sleep 5


INDI_VERSIONS=()
for v in "${SUPPORTED_INDI_VERSIONS[@]}"; do
    if [ "$v" == "$DETECTED_INDIVERSION" ]; then
        #INDI_VERSIONS[${#INDI_VERSIONS[@]}]="$v $v ON"

        INDI_VERSION=$v
        break
    else
        INDI_VERSIONS[${#INDI_VERSIONS[@]}]="$v $v OFF"
    fi
done



while [ -z "${INDI_VERSION:-}" ]; do
    # shellcheck disable=SC2068
    INDI_VERSION=$(whiptail --title "Installed INDI Version for pyindi-client" --nocancel --notags --radiolist "Press space to select" 0 0 0 ${INDI_VERSIONS[@]} 3>&1 1>&2 2>&3)
done

#echo "Selected: $INDI_VERSION"



if [ "$INDI_VERSION" == "2.0.0" ]; then
    pip3 install "$PYINDI_1_9_9"
elif [ "$INDI_VERSION" == "1.9.9" ]; then
    pip3 install "$PYINDI_1_9_9"
elif [ "$INDI_VERSION" == "1.9.8" ]; then
    pip3 install "$PYINDI_1_9_8"
elif [ "$INDI_VERSION" == "1.9.7" ]; then
    pip3 install "$PYINDI_1_9_8"
else
    # assuming skip
    echo "Skipping pyindi-client install"
fi



# get list of ccd drivers
INDI_CCD_DRIVERS=()
cd "$INDI_DRIVER_PATH" || catch_error
for I in indi_*_ccd indi_rpicam*; do
    INDI_CCD_DRIVERS[${#INDI_CCD_DRIVERS[@]}]="$I $I OFF"
done
cd "$OLDPWD" || catch_error

#echo ${INDI_CCD_DRIVERS[@]}


if [[ "$CAMERA_INTERFACE" == "indi" && "$INSTALL_INDISERVER" == "true" ]]; then
    while [ -z "${CCD_DRIVER:-}" ]; do
        # shellcheck disable=SC2068
        CCD_DRIVER=$(whiptail --title "Camera Driver" --nocancel --notags --radiolist "Press space to select" 0 0 0 ${INDI_CCD_DRIVERS[@]} 3>&1 1>&2 2>&3)
    done
else
    # simulator will not affect anything
    CCD_DRIVER=indi_simulator_ccd
fi

#echo $CCD_DRIVER



# get list of gps drivers
INDI_GPS_DRIVERS=("None None ON")
cd "$INDI_DRIVER_PATH" || catch_error
for I in indi_gps* indi_simulator_gps; do
    INDI_GPS_DRIVERS[${#INDI_GPS_DRIVERS[@]}]="$I $I OFF"
done
cd "$OLDPWD" || catch_error

#echo ${INDI_GPS_DRIVERS[@]}


if [[ "$INSTALL_INDISERVER" == "true" ]]; then
    while [ -z "${GPS_DRIVER:-}" ]; do
        # shellcheck disable=SC2068
        GPS_DRIVER=$(whiptail --title "GPS Driver" --nocancel --notags --radiolist "Press space to select" 0 0 0 ${INDI_GPS_DRIVERS[@]} 3>&1 1>&2 2>&3)
    done
fi

#echo $GPS_DRIVER

if [ "$GPS_DRIVER" == "None" ]; then
    # Value needs to be empty for None
    GPS_DRIVER=""
fi



# create users systemd folder
[[ ! -d "${HOME}/.config/systemd/user" ]] && mkdir -p "${HOME}/.config/systemd/user"


if [ "$INSTALL_INDISERVER" == "true" ]; then
    echo
    echo
    echo "**** Setting up indiserver service ****"
    TMP1=$(mktemp)
    sed \
     -e "s|%INDI_DRIVER_PATH%|$INDI_DRIVER_PATH|g" \
     -e "s|%INDISERVER_USER%|$USER|g" \
     -e "s|%INDI_CCD_DRIVER%|$CCD_DRIVER|g" \
     -e "s|%INDI_GPS_DRIVER%|$GPS_DRIVER|g" \
     "${ALLSKY_DIRECTORY}/service/indiserver.service" > "$TMP1"


    cp -f "$TMP1" "${HOME}/.config/systemd/user/${INDISERVER_SERVICE_NAME}.service"
    chmod 644 "${HOME}/.config/systemd/user/${INDISERVER_SERVICE_NAME}.service"
    [[ -f "$TMP1" ]] && rm -f "$TMP1"
else
    echo
    echo
    echo
    echo "! Bypassing indiserver setup"
fi


echo "**** Setting up indi-allsky service ****"
TMP2=$(mktemp)
sed \
 -e "s|%ALLSKY_USER%|$USER|g" \
 -e "s|%ALLSKY_DIRECTORY%|$ALLSKY_DIRECTORY|g" \
 -e "s|%ALLSKY_ETC%|$ALLSKY_ETC|g" \
 "${ALLSKY_DIRECTORY}/service/indi-allsky.service" > "$TMP2"

cp -f "$TMP2" "${HOME}/.config/systemd/user/${ALLSKY_SERVICE_NAME}.service"
chmod 644 "${HOME}/.config/systemd/user/${ALLSKY_SERVICE_NAME}.service"
[[ -f "$TMP2" ]] && rm -f "$TMP2"


echo "**** Setting up gunicorn service ****"
TMP5=$(mktemp)
sed \
 -e "s|%DB_FOLDER%|$DB_FOLDER|g" \
 -e "s|%GUNICORN_SERVICE_NAME%|$GUNICORN_SERVICE_NAME|g" \
 "${ALLSKY_DIRECTORY}/service/gunicorn-indi-allsky.socket" > "$TMP5"

cp -f "$TMP5" "${HOME}/.config/systemd/user/${GUNICORN_SERVICE_NAME}.socket"
chmod 644 "${HOME}/.config/systemd/user/${GUNICORN_SERVICE_NAME}.socket"
[[ -f "$TMP5" ]] && rm -f "$TMP5"

TMP6=$(mktemp)
sed \
 -e "s|%ALLSKY_USER%|$USER|g" \
 -e "s|%ALLSKY_DIRECTORY%|$ALLSKY_DIRECTORY|g" \
 -e "s|%GUNICORN_SERVICE_NAME%|$GUNICORN_SERVICE_NAME|g" \
 -e "s|%ALLSKY_ETC%|$ALLSKY_ETC|g" \
 "${ALLSKY_DIRECTORY}/service/gunicorn-indi-allsky.service" > "$TMP6"

cp -f "$TMP6" "${HOME}/.config/systemd/user/${GUNICORN_SERVICE_NAME}.service"
chmod 644 "${HOME}/.config/systemd/user/${GUNICORN_SERVICE_NAME}.service"
[[ -f "$TMP6" ]] && rm -f "$TMP6"


echo "**** Enabling services ****"
sudo loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable ${ALLSKY_SERVICE_NAME}.service
systemctl --user enable ${GUNICORN_SERVICE_NAME}.socket
systemctl --user enable ${GUNICORN_SERVICE_NAME}.service

if [ "$INSTALL_INDISERVER" == "true" ]; then
    systemctl --user enable ${INDISERVER_SERVICE_NAME}.service
fi


echo "**** Setup policy kit permissions ****"
TMP8=$(mktemp)
sed \
 -e "s|%ALLSKY_USER%|$USER|g" \
 "${ALLSKY_DIRECTORY}/service/90-org.aaronwmorris.indi-allsky.pkla" > "$TMP8"

sudo cp -f "$TMP8" "/etc/polkit-1/localauthority/50-local.d/90-org.aaronwmorris.indi-allsky.pkla"
sudo chown root:root "/etc/polkit-1/localauthority/50-local.d/90-org.aaronwmorris.indi-allsky.pkla"
sudo chmod 644 "/etc/polkit-1/localauthority/50-local.d/90-org.aaronwmorris.indi-allsky.pkla"
[[ -f "$TMP8" ]] && rm -f "$TMP8"


echo "**** Ensure user is a member of the systemd-journal group ****"
sudo usermod -a -G systemd-journal "$USER"


echo "**** Setup rsyslog logging ****"
[[ ! -d "/var/log/indi-allsky" ]] && sudo mkdir /var/log/indi-allsky
sudo chmod 755 /var/log/indi-allsky
sudo touch /var/log/indi-allsky/indi-allsky.log
sudo chmod 644 /var/log/indi-allsky/indi-allsky.log
sudo touch /var/log/indi-allsky/webapp-indi-allsky.log
sudo chmod 644 /var/log/indi-allsky/webapp-indi-allsky.log
sudo chown -R $RSYSLOG_USER:$RSYSLOG_GROUP /var/log/indi-allsky


# 10 prefix so they are process before the defaults in 50
sudo cp -f "${ALLSKY_DIRECTORY}/log/rsyslog_indi-allsky.conf" /etc/rsyslog.d/10-indi-allsky.conf
sudo chown root:root /etc/rsyslog.d/10-indi-allsky.conf
sudo chmod 644 /etc/rsyslog.d/10-indi-allsky.conf

# remove old version
[[ -f "/etc/rsyslog.d/indi-allsky.conf" ]] && sudo rm -f /etc/rsyslog.d/indi-allsky.conf

sudo systemctl restart rsyslog


sudo cp -f "${ALLSKY_DIRECTORY}/log/logrotate_indi-allsky" /etc/logrotate.d/indi-allsky
sudo chown root:root /etc/logrotate.d/indi-allsky
sudo chmod 644 /etc/logrotate.d/indi-allsky


echo "**** Indi-allsky config ****"
[[ ! -d "$ALLSKY_ETC" ]] && sudo mkdir "$ALLSKY_ETC"
sudo chown -R "$USER":"$PGRP" "$ALLSKY_ETC"
sudo chmod 775 "${ALLSKY_ETC}"


echo "**** Flask config ****"

while [ -z "${FLASK_AUTH_ALL_VIEWS:-}" ]; do
    if whiptail --title "Web Authentication" --yesno "Do you want to require authentication for all web site views?\n\nIf \"no\", privileged actions are still protected by authentication." 0 0 --defaultno; then
        FLASK_AUTH_ALL_VIEWS="true"
    else
        FLASK_AUTH_ALL_VIEWS="false"
    fi
done


TMP_FLASK=$(mktemp --suffix=.json)
TMP_FLASK_MERGE=$(mktemp --suffix=.json)

sed \
 -e "s|%SQLALCHEMY_DATABASE_URI%|$SQLALCHEMY_DATABASE_URI|g" \
 -e "s|%MIGRATION_FOLDER%|$MIGRATION_FOLDER|g" \
 -e "s|%ALLSKY_ETC%|$ALLSKY_ETC|g" \
 -e "s|%HTDOCS_FOLDER%|$HTDOCS_FOLDER|g" \
 -e "s|%INDISERVER_SERVICE_NAME%|$INDISERVER_SERVICE_NAME|g" \
 -e "s|%ALLSKY_SERVICE_NAME%|$ALLSKY_SERVICE_NAME|g" \
 -e "s|%GUNICORN_SERVICE_NAME%|$GUNICORN_SERVICE_NAME|g" \
 -e "s|%FLASK_AUTH_ALL_VIEWS%|$FLASK_AUTH_ALL_VIEWS|g" \
 "${ALLSKY_DIRECTORY}/flask.json_template" > "$TMP_FLASK"

# syntax check
json_pp < "$TMP_FLASK" >/dev/null


if [[ -f "${ALLSKY_ETC}/flask.json" ]]; then
    # make a backup
    cp -f "${ALLSKY_ETC}/flask.json" "${ALLSKY_ETC}/flask.json_old"
    chmod 640 "${ALLSKY_ETC}/flask.json_old"

    # attempt to merge configs giving preference to the original config (listed 2nd)
    jq -s '.[0] * .[1]' "$TMP_FLASK" "${ALLSKY_ETC}/flask.json" > "$TMP_FLASK_MERGE"
    cp -f "$TMP_FLASK_MERGE" "${ALLSKY_ETC}/flask.json"
else
    # new config
    cp -f "$TMP_FLASK" "${ALLSKY_ETC}/flask.json"
fi


SECRET_KEY=$(jq -r '.SECRET_KEY' "${ALLSKY_ETC}/flask.json")
if [ -z "$SECRET_KEY" ]; then
    # generate flask secret key
    SECRET_KEY=$(${PYTHON_BIN} -c 'import secrets; print(secrets.token_hex())')

    TMP_FLASK_SKEY=$(mktemp --suffix=.json)
    jq --arg secret_key "$SECRET_KEY" '.SECRET_KEY = $secret_key' "${ALLSKY_ETC}/flask.json" > "$TMP_FLASK_SKEY"
    cp -f "$TMP_FLASK_SKEY" "${ALLSKY_ETC}/flask.json"
    [[ -f "$TMP_FLASK_SKEY" ]] && rm -f "$TMP_FLASK_SKEY"
fi


PASSWORD_KEY=$(jq -r '.PASSWORD_KEY' "${ALLSKY_ETC}/flask.json")
if [ -z "$PASSWORD_KEY" ]; then
    # generate password key for encryption
    PASSWORD_KEY=$(${PYTHON_BIN} -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')

    TMP_FLASK_PKEY=$(mktemp --suffix=.json)
    jq --arg password_key "$PASSWORD_KEY" '.PASSWORD_KEY = $password_key' "${ALLSKY_ETC}/flask.json" > "$TMP_FLASK_PKEY"
    cp -f "$TMP_FLASK_PKEY" "${ALLSKY_ETC}/flask.json"
    [[ -f "$TMP_FLASK_PKEY" ]] && rm -f "$TMP_FLASK_PKEY"
fi


sudo chown "$USER":"$PGRP" "${ALLSKY_ETC}/flask.json"
sudo chmod 660 "${ALLSKY_ETC}/flask.json"

[[ -f "$TMP_FLASK" ]] && rm -f "$TMP_FLASK"
[[ -f "$TMP_FLASK_MERGE" ]] && rm -f "$TMP_FLASK_MERGE"



# create a backup of the key
if [ ! -f "${ALLSKY_ETC}/password_key_backup.json" ]; then
    jq -n --arg password_key "$PASSWORD_KEY" '.PASSWORD_KEY_BACKUP = $password_key' '{}' > "${ALLSKY_ETC}/password_key_backup.json"
fi

chmod 400 "${ALLSKY_ETC}/password_key_backup.json"



echo "**** Setup DB ****"
[[ ! -d "$DB_FOLDER" ]] && sudo mkdir "$DB_FOLDER"
sudo chmod 775 "$DB_FOLDER"
sudo chown -R "$USER":"$PGRP" "$DB_FOLDER"
[[ ! -d "${DB_FOLDER}/backup" ]] && sudo mkdir "${DB_FOLDER}/backup"
sudo chmod 775 "$DB_FOLDER/backup"
sudo chown "$USER":"$PGRP" "${DB_FOLDER}/backup"
if [[ -f "${DB_FILE}" ]]; then
    sudo chmod 664 "${DB_FILE}"
    sudo chown "$USER":"$PGRP" "${DB_FILE}"

    echo "**** Backup DB prior to migration ****"
    DB_BACKUP="${DB_FOLDER}/backup/backup_$(date +%Y%m%d_%H%M%S).sql.gz"
    sqlite3 "${DB_FILE}" .dump | gzip -c > "$DB_BACKUP"

    chmod 640 "$DB_BACKUP"
fi


# Setup migration folder
if [[ ! -d "$MIGRATION_FOLDER" ]]; then
    # Folder defined in flask config
    flask db init

    # Move migrations out of git checkout
    cd "${ALLSKY_DIRECTORY}/migrations/versions" || catch_error
    find . -type f -name "*.py" | cpio -pdmu "${MIGRATION_FOLDER}/versions"
    cd "$OLDPWD" || catch_error

    # Cleanup old files
    find "${ALLSKY_DIRECTORY}/migrations/versions" -type f -name "*.py" -exec rm -f {} \;
fi


flask db revision --autogenerate
flask db upgrade head


sudo chmod 664 "${DB_FILE}"
sudo chown "$USER":"$PGRP" "${DB_FILE}"


if [ -f "${ALLSKY_ETC}/config.json" ]; then
    echo
    echo
    echo "Configurations are now being stored in the database"
    echo "This script will move your existing configuration into"
    echo "the database."
    echo
    sleep 5

    "${ALLSKY_DIRECTORY}/config.py" load -c "${ALLSKY_ETC}/config.json"

    mv -f "${ALLSKY_ETC}/config.json" "${ALLSKY_ETC}/legacy_config.json"

    # Move old backup config
    if [ -f "${ALLSKY_ETC}/config.json_old" ]; then
        mv -f "${ALLSKY_ETC}/config.json_old" "${ALLSKY_ETC}/legacy_config.json_old"
    fi
fi


### Mysql
if [[ "$USE_MYSQL_DATABASE" == "true" ]]; then
    sudo cp -f "${ALLSKY_DIRECTORY}/service/mysql_indi-allsky.conf" "$MYSQL_ETC/mariadb.conf.d/90-mysql_indi-allsky.conf"
    sudo chown root:root "$MYSQL_ETC/mariadb.conf.d/90-mysql_indi-allsky.conf"
    sudo chmod 644 "$MYSQL_ETC/mariadb.conf.d/90-mysql_indi-allsky.conf"

    if [[ ! -d "$MYSQL_ETC/ssl" ]]; then
        sudo mkdir "$MYSQL_ETC/ssl"
    fi

    sudo chown root:root "$MYSQL_ETC/ssl"
    sudo chmod 755 "$MYSQL_ETC/ssl"


    if [[ ! -f "$MYSQL_ETC/ssl/indi-allsky_mysql.key" || ! -f "$MYSQL_ETC/ssl/indi-allsky_mysq.pem" ]]; then
        sudo rm -f "$MYSQL_ETC/ssl/indi-allsky_mysql.key"
        sudo rm -f "$MYSQL_ETC/ssl/indi-allsky_mysql.pem"

        SHORT_HOSTNAME=$(hostname -s)
        MYSQL_KEY_TMP=$(mktemp)
        MYSQL_CRT_TMP=$(mktemp)

        # sudo has problems with process substitution <()
        openssl req \
            -new \
            -newkey rsa:4096 \
            -sha512 \
            -days 3650 \
            -nodes \
            -x509 \
            -subj "/CN=${SHORT_HOSTNAME}.local" \
            -keyout "$MYSQL_KEY_TMP" \
            -out "$MYSQL_CRT_TMP" \
            -extensions san \
            -config <(cat /etc/ssl/openssl.cnf <(printf "\n[req]\ndistinguished_name=req\n[san]\nsubjectAltName=DNS:%s.local,DNS:%s,DNS:localhost" "$SHORT_HOSTNAME" "$SHORT_HOSTNAME"))

        sudo cp -f "$MYSQL_KEY_TMP" "$MYSQL_ETC/ssl/indi-allsky_mysql.key"
        sudo cp -f "$MYSQL_CRT_TMP" "$MYSQL_ETC/ssl/indi-allsky_mysql.pem"

        rm -f "$MYSQL_KEY_TMP"
        rm -f "$MYSQL_CRT_TMP"
    fi


    sudo chown root:root "$MYSQL_ETC/ssl/indi-allsky_mysql.key"
    sudo chmod 600 "$MYSQL_ETC/ssl/indi-allsky_mysql.key"
    sudo chown root:root "$MYSQL_ETC/ssl/indi-allsky_mysql.pem"
    sudo chmod 644 "$MYSQL_ETC/ssl/indi-allsky_mysql.pem"

    # system certificate store
    sudo cp -f "$MYSQL_ETC/ssl/indi-allsky_mysql.pem" /usr/local/share/ca-certificates/indi-allsky_mysql.crt
    sudo chown root:root /usr/local/share/ca-certificates/indi-allsky_mysql.crt
    sudo chmod 644 /usr/local/share/ca-certificates/indi-allsky_mysql.crt
    sudo update-ca-certificates


    sudo systemctl enable mariadb
    sudo systemctl restart mariadb
fi


# bootstrap initial config
"${ALLSKY_DIRECTORY}/config.py" bootstrap || true


# dump config for processing
TMP_CONFIG_DUMP=$(mktemp --suffix=.json)
"${ALLSKY_DIRECTORY}/config.py" dump > "$TMP_CONFIG_DUMP"



# Detect IMAGE_FOLDER
IMAGE_FOLDER=$(jq -r '.IMAGE_FOLDER' "$TMP_CONFIG_DUMP")

echo
echo
echo "Detected IMAGE_FOLDER: $IMAGE_FOLDER"
sleep 3


# replace the flask IMAGE_FOLDER
TMP_FLASK_3=$(mktemp --suffix=.json)
jq --arg image_folder "$IMAGE_FOLDER" '.INDI_ALLSKY_IMAGE_FOLDER = $image_folder' "${ALLSKY_ETC}/flask.json" > "$TMP_FLASK_3"
cp -f "$TMP_FLASK_3" "${ALLSKY_ETC}/flask.json"
[[ -f "$TMP_FLASK_3" ]] && rm -f "$TMP_FLASK_3"


TMP_GUNICORN=$(mktemp)
cat "${ALLSKY_DIRECTORY}/service/gunicorn.conf.py" > "$TMP_GUNICORN"

cp -f "$TMP_GUNICORN" "${ALLSKY_ETC}/gunicorn.conf.py"
chmod 644 "${ALLSKY_ETC}/gunicorn.conf.py"
[[ -f "$TMP_GUNICORN" ]] && rm -f "$TMP_GUNICORN"



if [[ "$ASTROBERRY" == "true" ]]; then
    echo "**** Disabling apache web server (Astroberry) ****"
    sudo systemctl stop apache2 || true
    sudo systemctl disable apache2 || true


    echo "**** Setup astroberry nginx ****"
    TMP3=$(mktemp)
    sed \
     -e "s|%ALLSKY_DIRECTORY%|$ALLSKY_DIRECTORY|g" \
     -e "s|%ALLSKY_ETC%|$ALLSKY_ETC|g" \
     -e "s|%DOCROOT_FOLDER%|$DOCROOT_FOLDER|g" \
     -e "s|%IMAGE_FOLDER%|$IMAGE_FOLDER|g" \
     -e "s|%HTTP_PORT%|$HTTP_PORT|g" \
     -e "s|%HTTPS_PORT%|$HTTPS_PORT|g" \
     -e "s|%UPSTREAM_SERVER%|unix:$DB_FOLDER/$GUNICORN_SERVICE_NAME.sock|g" \
     "${ALLSKY_DIRECTORY}/service/nginx_astroberry_ssl" > "$TMP3"


    #sudo cp -f /etc/nginx/sites-available/astroberry_ssl "/etc/nginx/sites-available/astroberry_ssl_$(date +%Y%m%d_%H%M%S)"
    sudo cp -f "$TMP3" /etc/nginx/sites-available/indi-allsky_ssl
    sudo chown root:root /etc/nginx/sites-available/indi-allsky_ssl
    sudo chmod 644 /etc/nginx/sites-available/indi-allsky_ssl
    sudo ln -s -f /etc/nginx/sites-available/indi-allsky_ssl /etc/nginx/sites-enabled/indi-allsky_ssl

    sudo systemctl enable nginx
    sudo systemctl restart nginx

else
    if systemctl -q is-active nginx; then
        echo "!!! WARNING - nginx is active - This might interfere with apache !!!"
        sleep 3
    fi

    if systemctl -q is-active lighttpd; then
        echo "!!! WARNING - lighttpd is active - This might interfere with apache !!!"
        sleep 3
    fi

    echo "**** Start apache2 service ****"
    TMP3=$(mktemp)
    sed \
     -e "s|%ALLSKY_DIRECTORY%|$ALLSKY_DIRECTORY|g" \
     -e "s|%ALLSKY_ETC%|$ALLSKY_ETC|g" \
     -e "s|%IMAGE_FOLDER%|$IMAGE_FOLDER|g" \
     -e "s|%HTTP_PORT%|$HTTP_PORT|g" \
     -e "s|%HTTPS_PORT%|$HTTPS_PORT|g" \
     -e "s|%UPSTREAM_SERVER%|unix:$DB_FOLDER/$GUNICORN_SERVICE_NAME.sock\|http://localhost/indi-allsky|g" \
     "${ALLSKY_DIRECTORY}/service/apache_indi-allsky.conf" > "$TMP3"


    if [[ "$DEBIAN_DISTRO" -eq 1 ]]; then
        sudo cp -f "$TMP3" /etc/apache2/sites-available/indi-allsky.conf
        sudo chown root:root /etc/apache2/sites-available/indi-allsky.conf
        sudo chmod 644 /etc/apache2/sites-available/indi-allsky.conf


        if [[ ! -d "/etc/apache2/ssl" ]]; then
            sudo mkdir /etc/apache2/ssl
        fi

        sudo chown root:root /etc/apache2/ssl
        sudo chmod 755 /etc/apache2/ssl


        if [[ ! -f "/etc/apache2/ssl/indi-allsky_apache.key" || ! -f "/etc/apache2/ssl/indi-allsky_apache.pem" ]]; then
            sudo rm -f /etc/apache2/ssl/indi-allsky_apache.key
            sudo rm -f /etc/apache2/ssl/indi-allsky_apache.pem

            SHORT_HOSTNAME=$(hostname -s)
            APACHE_KEY_TMP=$(mktemp)
            APACHE_CRT_TMP=$(mktemp)

            # sudo has problems with process substitution <()
            openssl req \
                -new \
                -newkey rsa:4096 \
                -sha512 \
                -days 3650 \
                -nodes \
                -x509 \
                -subj "/CN=${SHORT_HOSTNAME}.local" \
                -keyout "$APACHE_KEY_TMP" \
                -out "$APACHE_CRT_TMP" \
                -extensions san \
                -config <(cat /etc/ssl/openssl.cnf <(printf "\n[req]\ndistinguished_name=req\n[san]\nsubjectAltName=DNS:%s.local,DNS:%s,DNS:localhost" "$SHORT_HOSTNAME" "$SHORT_HOSTNAME"))

            sudo cp -f "$APACHE_KEY_TMP" /etc/apache2/ssl/indi-allsky_apache.key
            sudo cp -f "$APACHE_CRT_TMP" /etc/apache2/ssl/indi-allsky_apache.pem

            rm -f "$APACHE_KEY_TMP"
            rm -f "$APACHE_CRT_TMP"
        fi


        sudo chown root:root /etc/apache2/ssl/indi-allsky_apache.key
        sudo chmod 600 /etc/apache2/ssl/indi-allsky_apache.key
        sudo chown root:root /etc/apache2/ssl/indi-allsky_apache.pem
        sudo chmod 644 /etc/apache2/ssl/indi-allsky_apache.pem

        # system certificate store
        sudo cp -f /etc/apache2/ssl/indi-allsky_apache.pem /usr/local/share/ca-certificates/indi-allsky_apache.crt
        sudo chown root:root /usr/local/share/ca-certificates/indi-allsky_apache.crt
        sudo chmod 644 /usr/local/share/ca-certificates/indi-allsky_apache.crt
        sudo update-ca-certificates


        sudo a2enmod rewrite
        sudo a2enmod headers
        sudo a2enmod ssl
        #sudo a2enmod http2
        sudo a2enmod proxy
        sudo a2enmod proxy_http
        #sudo a2enmod proxy_http2

        sudo a2dissite 000-default
        sudo a2dissite default-ssl

        sudo a2ensite indi-allsky

        if [[ ! -f "/etc/apache2/ports.conf_pre_indiallsky" ]]; then
            sudo cp /etc/apache2/ports.conf /etc/apache2/ports.conf_pre_indiallsky

            # Comment out the Listen directives
            TMP9=$(mktemp)
            sed \
             -e 's|^\(.*\)[^#]\?\(listen.*\)|\1#\2|i' \
             /etc/apache2/ports.conf_pre_indiallsky > "$TMP9"

            sudo cp -f "$TMP9" /etc/apache2/ports.conf
            sudo chown root:root /etc/apache2/ports.conf
            sudo chmod 644 /etc/apache2/ports.conf
            [[ -f "$TMP9" ]] && rm -f "$TMP9"
        fi

        sudo systemctl enable apache2
        sudo systemctl restart apache2

    elif [[ "$REDHAT_DISTRO" -eq 1 ]]; then
        sudo cp -f "$TMP3" /etc/httpd/conf.d/indi-allsky.conf
        sudo chown root:root /etc/httpd/conf.d/indi-allsky.conf
        sudo chmod 644 /etc/httpd/conf.d/indi-allsky.conf

        sudo systemctl enable httpd
        sudo systemctl restart httpd
    fi

fi

[[ -f "$TMP3" ]] && rm -f "$TMP3"


# Allow web server access to mounted media
if [[ -d "/media/${USER}" ]]; then
    sudo chmod ugo+x "/media/${USER}"
fi


echo "**** Setup HTDOCS folder ****"
[[ ! -d "$HTDOCS_FOLDER" ]] && sudo mkdir "$HTDOCS_FOLDER"
sudo chmod 755 "$HTDOCS_FOLDER"
sudo chown -R "$USER":"$PGRP" "$HTDOCS_FOLDER"
[[ ! -d "$HTDOCS_FOLDER/js" ]] && mkdir "$HTDOCS_FOLDER/js"
chmod 775 "$HTDOCS_FOLDER/js"

for F in $HTDOCS_FILES; do
    cp -f "${ALLSKY_DIRECTORY}/html/${F}" "${HTDOCS_FOLDER}/${F}"
    chmod 664 "${HTDOCS_FOLDER}/${F}"
done


echo "**** Setup image folder ****"
[[ ! -d "$IMAGE_FOLDER" ]] && sudo mkdir -p "$IMAGE_FOLDER"
sudo chmod 775 "$IMAGE_FOLDER"
sudo chown -R "$USER":"$PGRP" "$IMAGE_FOLDER"
[[ ! -d "${IMAGE_FOLDER}/darks" ]] && mkdir "${IMAGE_FOLDER}/darks"
chmod 775 "${IMAGE_FOLDER}/darks"
[[ ! -d "${IMAGE_FOLDER}/export" ]] && mkdir "${IMAGE_FOLDER}/export"
chmod 775 "${IMAGE_FOLDER}/export"

if [ "$IMAGE_FOLDER" != "${ALLSKY_DIRECTORY}/html/images" ]; then
    for F in $IMAGE_FOLDER_FILES; do
        cp -f "${ALLSKY_DIRECTORY}/html/images/${F}" "${IMAGE_FOLDER}/${F}"
        chmod 664 "${IMAGE_FOLDER}/${F}"
    done
fi


if [ "$CCD_DRIVER" == "indi_rpicam" ]; then
    echo "**** Enable Raspberry Pi camera interface ****"
    sudo raspi-config nonint do_camera 0

    echo "**** Ensure user is a member of the video group ****"
    sudo usermod -a -G video "$USER"

    echo "**** Disable star eater algorithm ****"
    sudo vcdbg set imx477_dpc 0 || true

    echo "**** Setup disable cronjob at /etc/cron.d/disable_star_eater ****"
    echo "@reboot root /usr/bin/vcdbg set imx477_dpc 0 >/dev/null 2>&1" | sudo tee /etc/cron.d/disable_star_eater
    sudo chown root:root /etc/cron.d/disable_star_eater
    sudo chmod 644 /etc/cron.d/disable_star_eater

    echo
    echo
    echo "If this is the first time you have setup your Raspberry PI camera, please reboot when"
    echo "this script completes to enable the camera interface..."
    echo
    echo

    sleep 5
fi


if [[ "$CAMERA_INTERFACE" =~ "^libcamera" ]]; then
    echo "**** Enable Raspberry Pi camera interface ****"
    sudo raspi-config nonint do_camera 0

    echo "**** Ensure user is a member of the video group ****"
    sudo usermod -a -G video "$USER"

    echo "**** Disable star eater algorithm ****"
    echo "options imx477 dpc_enable=0" | sudo tee /etc/modprobe.d/imx477_dpc.conf
    sudo chown root:root /etc/modprobe.d/imx477_dpc.conf
    sudo chmod 644 /etc/modprobe.d/imx477_dpc.conf


    LIBCAMERA_CAMERAS="
        imx290
        imx378
        imx477
        imx477_noir
        imx519
        imx708
        imx708_noir
        imx708_wide
        imx708_wide_noir
    "

    for LIBCAMERA_JSON in $LIBCAMERA_CAMERAS; do
        JSON_FILE="/usr/share/libcamera/ipa/raspberrypi/${LIBCAMERA_JSON}.json"

        if [ -f "$JSON_FILE" ]; then
            echo "Disabling dpc in $JSON_FILE"

            TMP_JSON=$(mktemp)
            jq --argjson rpidpc_strength "$DPC_STRENGTH" '."rpi.dpc".strength = $rpidpc_strength' "$JSON_FILE" > "$TMP_JSON"
            sudo cp -f "$TMP_JSON" "$JSON_FILE"
            sudo chown root:root "$JSON_FILE"
            sudo chmod 644 "$JSON_FILE"
            [[ -f "$TMP_JSON" ]] && rm -f "$TMP_JSON"
        fi
    done


    echo
    echo
    echo "If this is the first time you have setup your Raspberry PI camera, please reboot when"
    echo "this script completes to enable the camera interface..."
    echo
    echo

    sleep 5
fi


# Disable raw frames with libcamera when running less than 1GB of memory
MEM_TOTAL=$(grep MemTotal /proc/meminfo | awk "{print \$2}")
if [ "$MEM_TOTAL" -lt "768000" ]; then
    TMP_LIBCAM_TYPE=$(mktemp --suffix=.json)
    jq --arg libcamera_file_type "jpg" '.LIBCAMERA.IMAGE_FILE_TYPE = $libcamera_file_type' "$TMP_CONFIG_DUMP" > "$TMP_LIBCAM_TYPE"

    cat "$TMP_LIBCAM_TYPE" > "$TMP_CONFIG_DUMP"

    [[ -f "$TMP_LIBCAM_TYPE" ]] && rm -f "$TMP_LIBCAM_TYPE"
fi

# 25% ffmpeg scaling with libcamera when running 1GB of memory
if [[ "$CAMERA_INTERFACE" == "libcamera_imx477" || "$CAMERA_INTERFACE" == "libcamera_imx378" || "$CAMERA_INTERFACE" == "libcamera_imx519" || "$CAMERA_INTERFACE" == "libcamera_imx708" || "$CAMERA_INTERFACE" == "libcamera_64mp_hawkeye" ]]; then
    if [ "$MEM_TOTAL" -lt "1536000" ]; then
        TMP_LIBCAM_FFMPEG=$(mktemp --suffix=.json)
        jq --arg ffmpeg_vfscale "iw*.25:ih*.25" '.FFMPEG_VFSCALE = $ffmpeg_vfscale' "$TMP_CONFIG_DUMP" > "$TMP_LIBCAM_FFMPEG"

        cat "$TMP_LIBCAM_FFMPEG" > "$TMP_CONFIG_DUMP"

        [[ -f "$TMP_LIBCAM_FFMPEG" ]] && rm -f "$TMP_LIBCAM_FFMPEG"
    fi
fi


echo "**** Ensure user is a member of the dialout group ****"
# for GPS and serial port access
sudo usermod -a -G dialout "$USER"


echo "**** Disabling Thomas Jacquin's allsky (ignore errors) ****"
# Not trying to push out the competition, these just cannot run at the same time :-)
sudo systemctl stop allsky || true
sudo systemctl disable allsky || true


echo "**** Starting ${GUNICORN_SERVICE_NAME}.socket"
# this needs to happen after creating the $DB_FOLDER
systemctl --user start ${GUNICORN_SERVICE_NAME}.socket


echo "**** Update config camera interface ****"
TMP_CAMERA_INT=$(mktemp --suffix=.json)
jq --arg camera_interface "$CAMERA_INTERFACE" '.CAMERA_INTERFACE = $camera_interface' "$TMP_CONFIG_DUMP" > "$TMP_CAMERA_INT"

cat "$TMP_CAMERA_INT" > "$TMP_CONFIG_DUMP"

[[ -f "$TMP_CAMERA_INT" ]] && rm -f "$TMP_CAMERA_INT"


# final config syntax check
json_pp < "${ALLSKY_ETC}/flask.json" > /dev/null


USER_COUNT=$("${ALLSKY_DIRECTORY}/config.py" user_count)
# there is a system user
if [ "$USER_COUNT" -le 1 ]; then
    while [ -z "${WEB_USER:-}" ]; do
        # shellcheck disable=SC2068
        WEB_USER=$(whiptail --title "Username" --nocancel --inputbox "Please enter a username to login" 0 0 3>&1 1>&2 2>&3)
    done

    while [ -z "${WEB_PASS:-}" ]; do
        # shellcheck disable=SC2068
        WEB_PASS=$(whiptail --title "Password" --nocancel --passwordbox "Please enter the password (8+ chars)" 0 0 3>&1 1>&2 2>&3)

        if [ "${#WEB_PASS}" -lt 8 ]; then
            WEB_PASS=""
            whiptail --msgbox "Error: Password needs to be at least 8 characters" 0 0
            continue
        fi


        WEB_PASS2=$(whiptail --title "Password (#2)" --nocancel --passwordbox "Please enter the password (8+ chars)" 0 0 3>&1 1>&2 2>&3)

        if [ "$WEB_PASS" != "$WEB_PASS2" ]; then
            WEB_PASS=""
            whiptail --msgbox "Error: Passwords did not match" 0 0
            continue
        fi

    done

    while [ -z "${WEB_NAME:-}" ]; do
        # shellcheck disable=SC2068
        WEB_NAME=$(whiptail --title "Full Name" --nocancel --inputbox "Please enter the users name" 0 0 3>&1 1>&2 2>&3)
    done

    while [ -z "${WEB_EMAIL:-}" ]; do
        # shellcheck disable=SC2068
        WEB_EMAIL=$(whiptail --title "Full Name" --nocancel --inputbox "Please enter the users email" 0 0 3>&1 1>&2 2>&3)
    done

    "$ALLSKY_DIRECTORY/misc/usertool.py" adduser -u "$WEB_USER" -p "$WEB_PASS" -f "$WEB_NAME" -e "$WEB_EMAIL"
    "$ALLSKY_DIRECTORY/misc/usertool.py" setadmin -u "$WEB_USER"
fi


# load all changes
"${ALLSKY_DIRECTORY}/config.py" load -c "$TMP_CONFIG_DUMP" --force
[[ -f "$TMP_CONFIG_DUMP" ]] && rm -f "$TMP_CONFIG_DUMP"


echo
echo
echo
echo
echo "*** Configurations are now stored in the database and *NOT* /etc/indi-allsky/config.json ***"
echo
echo "Services can be started at the command line or can be started from the web interface"
echo
echo "    systemctl --user start indiserver"
echo "    systemctl --user start indi-allsky"
echo
echo
echo "The web interface may be accessed with the following URL"
echo " (You may have to manually access by IP)"
echo

if [[ "$HTTPS_PORT" -eq 443 ]]; then
    echo "    https://$(hostname -s).local/indi-allsky/"
else
    echo "    https://$(hostname -s).local:$HTTPS_PORT/indi-allsky/"

fi

END_TIME=$(date +%s)

echo
echo
echo "Completed in $((END_TIME - START_TIME))s"
echo

echo
echo "Enjoy!"
