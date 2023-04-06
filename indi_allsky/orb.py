import cv2
import math
import logging

import ephem

logger = logging.getLogger('indi_allsky')



class IndiAllskyOrbGenerator(object):

    line_thickness = 2


    def __init__(self, config):
        self.config = config


    def drawOrbsHourAngle(self, data_bytes, utcnow, color_bgr, obs, sun, moon):
        image_height, image_width = data_bytes.shape[:2]

        obs.date = utcnow
        sun.compute(obs)
        sunOrbX, sunOrbY = self.getOrbHourAngleXY(sun, obs, (image_height, image_width))

        obs.date = utcnow
        moon.compute(obs)
        moonOrbX, moonOrbY = self.getOrbHourAngleXY(moon, obs, (image_height, image_width))


        # Sun
        sun_color_bgr = list(self.config['ORB_PROPERTIES']['SUN_COLOR'])
        sun_color_bgr.reverse()

        self.drawEdgeCircle(data_bytes, (sunOrbX, sunOrbY), sun_color_bgr)


        # Moon
        moon_color_bgr = list(self.config['ORB_PROPERTIES']['MOON_COLOR'])
        moon_color_bgr.reverse()

        self.drawEdgeCircle(data_bytes, (moonOrbX, moonOrbY), moon_color_bgr)




        obs.date = utcnow  # reset
        sun.compute(obs)

        # Sunrise
        try:
            obs.horizon = math.radians(0.0)
            sun_rise_date = obs.next_rising(sun, use_center=True)

            obs.date = sun_rise_date
            sun.compute(obs)
            sunRiseX, sunRiseY = self.getOrbHourAngleXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunRiseX, sunRiseY), (100, 100, 100))
        except ephem.NeverUpError:
            # northern hemisphere
            pass
        except ephem.AlwaysUpError:
            # southern hemisphere
            pass


        obs.date = utcnow  # reset
        sun.compute(obs)

        # Civil dawn
        try:
            obs.horizon = math.radians(-6.0)
            sun_civilDawn_date = obs.next_rising(sun, use_center=True)

            obs.date = sun_civilDawn_date
            sun.compute(obs)
            sunCivilDawnX, sunCivilDawnY = self.getOrbHourAngleXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunCivilDawnX, sunCivilDawnY), (100, 100, 100))
        except ephem.NeverUpError:
            # northern hemisphere
            pass
        except ephem.AlwaysUpError:
            # southern hemisphere
            pass


        obs.date = utcnow  # reset
        sun.compute(obs)

        # Nautical dawn
        try:
            obs.horizon = math.radians(-12.0)
            sun_nauticalDawn_date = obs.next_rising(sun, use_center=True)

            obs.date = sun_nauticalDawn_date
            sun.compute(obs)
            sunNauticalDawnX, sunNauticalDawnY = self.getOrbHourAngleXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunNauticalDawnX, sunNauticalDawnY), (100, 100, 100))
        except ephem.NeverUpError:
            # northern hemisphere
            pass
        except ephem.AlwaysUpError:
            # southern hemisphere
            pass


        obs.date = utcnow  # reset
        sun.compute(obs)

        # Astronomical dawn
        try:
            obs.horizon = math.radians(-18.0)
            sun_astroDawn_date = obs.next_rising(sun, use_center=True)

            obs.date = sun_astroDawn_date
            sun.compute(obs)
            sunAstroDawnX, sunAstroDawnY = self.getOrbHourAngleXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunAstroDawnX, sunAstroDawnY), (100, 100, 100))
        except ephem.NeverUpError:
            # northern hemisphere
            pass
        except ephem.AlwaysUpError:
            # southern hemisphere
            pass


        obs.date = utcnow  # reset
        sun.compute(obs)

        # Sunset
        try:
            obs.horizon = math.radians(0.0)
            sun_set_date = obs.next_setting(sun, use_center=True)

            obs.date = sun_set_date
            sun.compute(obs)
            sunSunSetX, sunSunSetY = self.getOrbHourAngleXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunSunSetX, sunSunSetY), (100, 100, 100))
        except ephem.AlwaysUpError:
            # northern hemisphere
            pass
        except ephem.NeverUpError:
            # southern hemisphere
            pass


        obs.date = utcnow  # reset
        sun.compute(obs)

        # Civil twilight
        try:
            obs.horizon = math.radians(-6.0)
            sun_civilTwilight_date = obs.next_setting(sun, use_center=True)

            obs.date = sun_civilTwilight_date
            sun.compute(obs)
            sunCivilTwilightX, sunCivilTwilightY = self.getOrbHourAngleXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunCivilTwilightX, sunCivilTwilightY), (100, 100, 100))
        except ephem.AlwaysUpError:
            # northern hemisphere
            pass
        except ephem.NeverUpError:
            # southern hemisphere
            pass


        obs.date = utcnow  # reset
        sun.compute(obs)

        # Nautical twilight
        try:
            obs.horizon = math.radians(-12.0)
            sun_nauticalTwilight_date = obs.next_setting(sun, use_center=True)

            obs.date = sun_nauticalTwilight_date
            sun.compute(obs)
            sunNauticalTwilightX, sunNauticalTwilightY = self.getOrbHourAngleXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunNauticalTwilightX, sunNauticalTwilightY), (100, 100, 100))
        except ephem.AlwaysUpError:
            # northern hemisphere
            pass
        except ephem.NeverUpError:
            # southern hemisphere
            pass


        obs.date = utcnow  # reset
        sun.compute(obs)

        # Astronomical twilight
        try:
            obs.horizon = math.radians(-18.0)
            sun_astroTwilight_date = obs.next_setting(sun, use_center=True)

            obs.date = sun_astroTwilight_date
            sun.compute(obs)
            sunAstroTwilightX, sunAstroTwilightY = self.getOrbHourAngleXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunAstroTwilightX, sunAstroTwilightY), (100, 100, 100))
        except ephem.AlwaysUpError:
            # northern hemisphere
            pass
        except ephem.NeverUpError:
            # southern hemisphere
            pass


        obs.date = utcnow  # reset
        sun.compute(obs)

        # Night/Day boundary
        try:
            obs.horizon = math.radians(self.config['NIGHT_SUN_ALT_DEG'])
            sun_nightDay_date = obs.next_rising(sun, use_center=True)

            obs.date = sun_nightDay_date
            sun.compute(obs)
            sunNightDayX, sunNightDayY = self.getOrbHourAngleXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunNightDayX, sunNightDayY), color_bgr)
        except ephem.AlwaysUpError:
            # northern hemisphere
            pass
        except ephem.NeverUpError:
            # southern hemisphere
            pass


        obs.date = utcnow  # reset
        sun.compute(obs)

        # Day/Night boundary
        try:
            obs.horizon = math.radians(self.config['NIGHT_SUN_ALT_DEG'])
            sun_dayNight_date = obs.next_setting(sun, use_center=True)

            obs.date = sun_dayNight_date
            sun.compute(obs)
            sunDayNightX, sunDayNightY = self.getOrbHourAngleXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunDayNightX, sunDayNightY), color_bgr)
        except ephem.AlwaysUpError:
            # northern hemisphere
            pass
        except ephem.NeverUpError:
            # southern hemisphere
            pass



    def getOrbHourAngleXY(self, skyObj, obs, image_size):
        image_height, image_width = image_size

        ha_rad = obs.sidereal_time() - skyObj.ra
        ha_deg = math.degrees(ha_rad)

        if ha_deg < -180:
            ha_deg = 360 + ha_deg
        elif ha_deg > 180:
            ha_deg = -360 + ha_deg
        else:
            pass

        #logger.info('%s hour angle: %0.2f @ %s', skyObj.name, ha_deg, obs.date)

        abs_ha_deg = abs(ha_deg)
        perimeter_half = image_width + image_height

        mapped_ha_deg = self.remap(abs_ha_deg, 0.0, 180.0, 0.0, perimeter_half)
        #logger.info('Mapped hour angle: %0.2f', mapped_ha_deg)

        ### The image perimeter is mapped to the hour angle for the X,Y coordinates
        if mapped_ha_deg < (image_width / 2) and ha_deg < 0:
            #logger.info('Top right')
            x = (image_width / 2) + mapped_ha_deg
            y = 0
        elif mapped_ha_deg < (image_width / 2) and ha_deg > 0:
            #logger.info('Top left')
            x = (image_width / 2) - mapped_ha_deg
            y = 0
        elif mapped_ha_deg > ((image_width / 2) + image_height) and ha_deg < 0:
            #logger.info('Bottom right')
            x = image_width - (mapped_ha_deg - (image_height + (image_width / 2)))
            y = image_height
        elif mapped_ha_deg > ((image_width / 2) + image_height) and ha_deg > 0:
            #logger.info('Bottom left')
            x = mapped_ha_deg - (image_height + (image_width / 2))
            y = image_height
        elif ha_deg < 0:
            #logger.info('Right')
            x = image_width
            y = mapped_ha_deg - (image_width / 2)
        elif ha_deg > 0:
            #logger.info('Left')
            x = 0
            y = mapped_ha_deg - (image_width / 2)
        else:
            raise Exception('This cannot happen')


        #logger.info('Orb: %0.2f x %0.2f', x, y)

        return int(x), int(y)


    def drawOrbsAzimuth(self, data_bytes, utcnow, color_bgr, obs, sun, moon):
        image_height, image_width = data_bytes.shape[:2]

        obs.date = utcnow
        sun.compute(obs)
        sunOrbX, sunOrbY = self.getOrbAzimuthXY(sun, obs, (image_height, image_width))

        obs.date = utcnow
        moon.compute(obs)
        moonOrbX, moonOrbY = self.getOrbAzimuthXY(moon, obs, (image_height, image_width))


        # Sun
        sun_color_bgr = list(self.config['ORB_PROPERTIES']['SUN_COLOR'])
        sun_color_bgr.reverse()

        self.drawEdgeCircle(data_bytes, (sunOrbX, sunOrbY), sun_color_bgr)


        # Moon
        moon_color_bgr = list(self.config['ORB_PROPERTIES']['MOON_COLOR'])
        moon_color_bgr.reverse()

        self.drawEdgeCircle(data_bytes, (moonOrbX, moonOrbY), moon_color_bgr)


        obs.date = utcnow  # reset
        sun.compute(obs)

        # Sunrise
        try:
            obs.horizon = math.radians(0.0)
            sun_rise_date = obs.next_rising(sun, use_center=True)

            obs.date = sun_rise_date
            sun.compute(obs)
            sunSunRiseX, sunSunRiseY = self.getOrbAzimuthXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunSunRiseX, sunSunRiseY), (100, 100, 100))
        except ephem.NeverUpError:
            # northern hemisphere
            pass
        except ephem.AlwaysUpError:
            # southern hemisphere
            pass


        obs.date = utcnow  # reset
        sun.compute(obs)

        # Civil dawn
        try:
            obs.horizon = math.radians(-6.0)
            sun_civilDawn_date = obs.next_rising(sun, use_center=True)

            obs.date = sun_civilDawn_date
            sun.compute(obs)
            sunCivilDawnX, sunCivilDawnY = self.getOrbAzimuthXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunCivilDawnX, sunCivilDawnY), (100, 100, 100))
        except ephem.NeverUpError:
            # northern hemisphere
            pass
        except ephem.AlwaysUpError:
            # southern hemisphere
            pass


        obs.date = utcnow  # reset
        sun.compute(obs)

        # Nautical dawn
        try:
            obs.horizon = math.radians(-12.0)
            sun_nauticalDawn_date = obs.next_rising(sun, use_center=True)

            obs.date = sun_nauticalDawn_date
            sun.compute(obs)
            sunNauticalDawnX, sunNauticalDawnY = self.getOrbAzimuthXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunNauticalDawnX, sunNauticalDawnY), (100, 100, 100))
        except ephem.NeverUpError:
            # northern hemisphere
            pass
        except ephem.AlwaysUpError:
            # southern hemisphere
            pass


        obs.date = utcnow  # reset
        sun.compute(obs)

        # Astronomical dawn
        try:
            obs.horizon = math.radians(-18.0)
            sun_astroDawn_date = obs.next_rising(sun, use_center=True)

            obs.date = sun_astroDawn_date
            sun.compute(obs)
            sunAstroDawnX, sunAstroDawnY = self.getOrbAzimuthXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunAstroDawnX, sunAstroDawnY), (100, 100, 100))
        except ephem.NeverUpError:
            # northern hemisphere
            pass
        except ephem.AlwaysUpError:
            # southern hemisphere
            pass


        obs.date = utcnow  # reset
        sun.compute(obs)

        # Sunset
        try:
            obs.horizon = math.radians(0.0)
            sun_set_date = obs.next_setting(sun, use_center=True)

            obs.date = sun_set_date
            sun.compute(obs)
            sunSunSetX, sunSunSetY = self.getOrbAzimuthXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunSunSetX, sunSunSetY), (100, 100, 100))
        except ephem.AlwaysUpError:
            # northern hemisphere
            pass
        except ephem.NeverUpError:
            # southern hemisphere
            pass


        obs.date = utcnow  # reset
        sun.compute(obs)

        # Civil twilight
        try:
            obs.horizon = math.radians(-6.0)
            sun_civilTwilight_date = obs.next_setting(sun, use_center=True)

            obs.date = sun_civilTwilight_date
            sun.compute(obs)
            sunCivilTwilightX, sunCivilTwilightY = self.getOrbAzimuthXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunCivilTwilightX, sunCivilTwilightY), (100, 100, 100))
        except ephem.AlwaysUpError:
            # northern hemisphere
            pass
        except ephem.NeverUpError:
            # southern hemisphere
            pass


        obs.date = utcnow  # reset
        sun.compute(obs)

        # Nautical twilight
        try:
            obs.horizon = math.radians(-12.0)
            sun_nauticalTwilight_date = obs.next_setting(sun, use_center=True)

            obs.date = sun_nauticalTwilight_date
            sun.compute(obs)
            sunNauticalTwilightX, sunNauticalTwilightY = self.getOrbAzimuthXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunNauticalTwilightX, sunNauticalTwilightY), (100, 100, 100))
        except ephem.AlwaysUpError:
            # northern hemisphere
            pass
        except ephem.NeverUpError:
            # southern hemisphere
            pass


        obs.date = utcnow  # reset
        sun.compute(obs)

        # Astronomical twilight
        try:
            obs.horizon = math.radians(-18.0)
            sun_astroTwilight_date = obs.next_setting(sun, use_center=True)

            obs.date = sun_astroTwilight_date
            sun.compute(obs)
            sunAstroTwilightX, sunAstroTwilightY = self.getOrbAzimuthXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunAstroTwilightX, sunAstroTwilightY), (100, 100, 100))
        except ephem.AlwaysUpError:
            # northern hemisphere
            pass
        except ephem.NeverUpError:
            # southern hemisphere
            pass


        obs.date = utcnow  # reset
        sun.compute(obs)

        # Night/Day
        try:
            obs.horizon = math.radians(self.config['NIGHT_SUN_ALT_DEG'])
            sun_nightDay_date = obs.next_rising(sun, use_center=True)

            obs.date = sun_nightDay_date
            sun.compute(obs)
            sunNightDayX, sunNightDayY = self.getOrbAzimuthXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunNightDayX, sunNightDayY), color_bgr)
        except ephem.NeverUpError:
            # northern hemisphere
            pass
        except ephem.AlwaysUpError:
            # southern hemisphere
            pass


        obs.date = utcnow  # reset
        sun.compute(obs)

        # Day/Night
        try:
            obs.horizon = math.radians(self.config['NIGHT_SUN_ALT_DEG'])
            sun_dayNight_date = obs.next_setting(sun, use_center=True)

            obs.date = sun_dayNight_date
            sun.compute(obs)
            sunDayNightX, sunDayNightY = self.getOrbAzimuthXY(sun, obs, (image_height, image_width))

            self.drawEdgeLine(data_bytes, (sunDayNightX, sunDayNightY), color_bgr)
        except ephem.NeverUpError:
            # northern hemisphere
            pass
        except ephem.AlwaysUpError:
            # southern hemisphere
            pass


    def getOrbAzimuthXY(self, skyObj, obs, image_size):
        image_height, image_width = image_size

        az_deg = math.degrees(skyObj.az)


        # For now, I am too lazy to fix the calculations below (pulled from hour angle code)
        if az_deg < 180:
            az_deg = az_deg * -1
        elif az_deg > 180:
            az_deg = (-360 + az_deg) * -1


        #logger.info('%s azimuth: %0.2f @ %s', skyObj.name, az_deg, obs.date)

        abs_az_deg = abs(az_deg)
        perimeter_half = image_width + image_height

        mapped_az_deg = self.remap(abs_az_deg, 0.0, 180.0, 0.0, perimeter_half)
        #logger.info('Mapped azimuth: %0.2f', mapped_az_deg)

        ### The image perimeter is mapped to the azimuth for the X,Y coordinates
        if mapped_az_deg < (image_width / 2) and az_deg < 0:
            #logger.info('Top right')
            x = (image_width / 2) + mapped_az_deg
            y = 0
        elif mapped_az_deg < (image_width / 2) and az_deg > 0:
            #logger.info('Top left')
            x = (image_width / 2) - mapped_az_deg
            y = 0
        elif mapped_az_deg > ((image_width / 2) + image_height) and az_deg < 0:
            #logger.info('Bottom right')
            x = image_width - (mapped_az_deg - (image_height + (image_width / 2)))
            y = image_height
        elif mapped_az_deg > ((image_width / 2) + image_height) and az_deg > 0:
            #logger.info('Bottom left')
            x = mapped_az_deg - (image_height + (image_width / 2))
            y = image_height
        elif az_deg < 0:
            #logger.info('Right')
            x = image_width
            y = mapped_az_deg - (image_width / 2)
        elif az_deg > 0:
            #logger.info('Left')
            x = 0
            y = mapped_az_deg - (image_width / 2)
        else:
            raise Exception('This cannot happen')


        #logger.info('Orb: %0.2f x %0.2f', x, y)

        return int(x), int(y)


    def drawOrbsAltitude(self, data_bytes, utcnow, color_bgr, obs, sun, moon):
        image_height, image_width = data_bytes.shape[:2]

        obs.date = utcnow
        sun.compute(obs)
        sunOrbX, sunOrbY = self.getOrbAltitudeXY(sun, obs, (image_height, image_width), utcnow)

        obs.date = utcnow
        moon.compute(obs)
        moonOrbX, moonOrbY = self.getOrbAltitudeXY(moon, obs, (image_height, image_width), utcnow)


        # Sun
        sun_color_bgr = list(self.config['ORB_PROPERTIES']['SUN_COLOR'])
        sun_color_bgr.reverse()

        self.drawEdgeCircle(data_bytes, (sunOrbX, sunOrbY), sun_color_bgr)


        # Moon
        moon_color_bgr = list(self.config['ORB_PROPERTIES']['MOON_COLOR'])
        moon_color_bgr.reverse()

        self.drawEdgeCircle(data_bytes, (moonOrbX, moonOrbY), moon_color_bgr)


        # Sunrise
        sunRiseX = image_width
        sunRiseY = self.remap(0.0, -90.0, 90.0, 0.0, image_height)
        sunRiseY = image_height - sunRiseY  # need to map from the top down

        self.drawEdgeLine(data_bytes, (sunRiseX, int(sunRiseY)), (100, 100, 100))


        # Civil dawn
        sunCivilDawnX = image_width
        sunCivilDawnY = self.remap(-6.0, -90.0, 90.0, 0.0, image_height)
        sunCivilDawnY = image_height - sunCivilDawnY  # need to map from the top down

        self.drawEdgeLine(data_bytes, (sunCivilDawnX, int(sunCivilDawnY)), (100, 100, 100))


        # Nautical dawn
        sunNauticalDawnX = image_width
        sunNauticalDawnY = self.remap(-12.0, -90.0, 90.0, 0.0, image_height)
        sunNauticalDawnY = image_height - sunNauticalDawnY  # need to map from the top down

        self.drawEdgeLine(data_bytes, (sunNauticalDawnX, int(sunNauticalDawnY)), (100, 100, 100))


        # Astronomical dawn
        sunAstroDawnX = image_width
        sunAstroDawnY = self.remap(-18.0, -90.0, 90.0, 0.0, image_height)
        sunAstroDawnY = image_height - sunAstroDawnY  # need to map from the top down

        self.drawEdgeLine(data_bytes, (sunAstroDawnX, int(sunAstroDawnY)), (100, 100, 100))


        # Sunset
        sunSetX = 0
        sunSetY = sunRiseY  # reuse

        self.drawEdgeLine(data_bytes, (sunSetX, int(sunSetY)), (100, 100, 100))


        # Civil twilight
        sunCivilTwilightX = 0
        sunCivilTwilightY = sunCivilDawnY  # reuse

        self.drawEdgeLine(data_bytes, (sunCivilTwilightX, int(sunCivilTwilightY)), (100, 100, 100))


        # Nautical twilight
        sunNauticalTwilightX = 0
        sunNauticalTwilightY = sunNauticalDawnY  # reuse

        self.drawEdgeLine(data_bytes, (sunNauticalTwilightX, int(sunNauticalTwilightY)), (100, 100, 100))


        # Astronomical twilight
        sunAstroTwilightX = 0
        sunAstroTwilightY = sunAstroDawnY  # reuse

        self.drawEdgeLine(data_bytes, (sunAstroTwilightX, int(sunAstroTwilightY)), (100, 100, 100))


        # Night/Day
        sunNightDayX = image_width
        sunNightDayY = self.remap(self.config['NIGHT_SUN_ALT_DEG'], -90.0, 90.0, 0.0, image_height)
        sunNightDayY = image_height - sunNightDayY  # need to map from the top down

        self.drawEdgeLine(data_bytes, (sunNightDayX, int(sunNightDayY)), color_bgr)


        # Day/Night
        sunDayNightX = 0
        sunDayNightY = sunNightDayY  # reuse

        self.drawEdgeLine(data_bytes, (sunDayNightX, int(sunDayNightY)), color_bgr)


    def getOrbAltitudeXY(self, skyObj, obs, image_size, utcnow):
        image_height, image_width = image_size

        alt_deg = math.degrees(skyObj.alt)

        skyObj_transit_date = obs.next_transit(skyObj).datetime()
        skyObj_transit_delta = skyObj_transit_date - utcnow
        if skyObj_transit_delta.seconds < 43200:  # 12 hours
            # rising, put on right
            x = image_width
        else:
            # setting, put on left
            x = 0

        y = self.remap(alt_deg, -90.0, 90.0, 0.0, image_height)
        y = image_height - y  # need to map from the top down

        return int(x), int(y)


    def drawEdgeCircle(self, data_bytes, pt, color_bgr):
        if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
            cv2.circle(
                img=data_bytes,
                center=pt,
                radius=self.config['ORB_PROPERTIES']['RADIUS'],
                color=(0, 0, 0),
                thickness=cv2.FILLED,
            )

        cv2.circle(
            img=data_bytes,
            center=pt,
            radius=self.config['ORB_PROPERTIES']['RADIUS'] - 1,
            color=tuple(color_bgr),
            thickness=cv2.FILLED,
        )


    def drawEdgeLine(self, data_bytes, pt, color_bgr):
        lineType = getattr(cv2, self.config['TEXT_PROPERTIES']['FONT_AA'])

        image_height, image_width = data_bytes.shape[:2]

        line_length = int(self.config['ORB_PROPERTIES']['RADIUS'] / 2)

        x, y = pt
        if x == 0 or x == image_width:
            # line is on the left or right
            x1 = x - line_length
            y1 = y
            x2 = x + line_length
            y2 = y
        else:
            # line is on the top or bottom
            x1 = x
            y1 = y - line_length
            x2 = x
            y2 = y + line_length


        if self.config['TEXT_PROPERTIES']['FONT_OUTLINE']:
            cv2.line(
                img=data_bytes,
                pt1=(x1, y1),
                pt2=(x2, y2),
                color=(0, 0, 0),
                thickness=self.line_thickness + 1,
                lineType=lineType,
            )  # black outline
        cv2.line(
            img=data_bytes,
            pt1=(x1, y1),
            pt2=(x2, y2),
            color=tuple(color_bgr),
            thickness=self.line_thickness,
            lineType=lineType,
        )



    def remap(self, x, in_min, in_max, out_min, out_max):
        return (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min

