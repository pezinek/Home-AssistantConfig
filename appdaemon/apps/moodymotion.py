import appdaemon.appapi as appapi

#
#
# Args: 
#
# light: light to turn on/off
# motion_detector: binary_sensor 
# luminosity_sensor: luxmeter
# mode_selector: input_select
# modes: comma separated list of modes we react on (from <mode_selector>)
# <mode>_luminosity: threshold on <luminosity_sensor>, we react only if
#                    we are above this value
# <mode>_off_timeout: treshold after which light is turned off if no motion
# <mode>_color: Color to use when turning the light on
#
# TODO: listen to light state changes and acc accordingly if humans
#       interfere manually, e.g. if someone turns on/off the light 
#       manually, cancell the turn off timer

class ModeSettings(object):
  def __init__(self, luminosity, off_timeout, color):
        self.luminosity = luminosity
        self.off_timeout = off_timeout
        self.color = color

  def __repr__(self):
        return str(self.__dict__)


class MoodyMotionTrigger(appapi.AppDaemon):

  #def log(self, message, level="INFO"):
  #    try:
  #      if self.args['debug']:
  #         return super().log(message, level=level)
  #    except KeyError:
  #      pass
  #
  #    return None

  def initialize(self):

     #self.log("Init started")

     self.on_handle = None
     self.off_handle = None
     self.luminosity = None
     self.mode = None
     self.light = None

     self._load_modes()

     self.light = self.get_state(self.args['light'])
     self.listen_state(self.light_on, self.args['light'], new='on')
     self.listen_state(self.light_off, self.args['light'], new='off')

     lum = self.get_state(self.args['luminosity_sensor'])
     self.luminosity_changed(self.args['luminosity_sensor'], None, lum, lum, {})
     self.listen_state(self.luminosity_changed, self.args['luminosity_sensor'])

     mode = self.get_state(self.args['mode_selector'])
     self.mode_changed(self.args['mode_selector'], None, mode, mode, {})
     self.listen_state(self.mode_changed, self.args['mode_selector'])

     #self.log("Init complete: (modes: {})".format(self.modes))

  def _load_modes(self):
     self.modes = {}
     for mode in self.args['modes'].split():
         self.modes[mode] = ModeSettings(
              float(self.args['{}_luminosity'.format(mode)]),
              float(self.args['{}_off_timeout'.format(mode)]),
              [ int(x.strip(',][')) for x in self.args['{}_color'.format(mode)].split() ] 
         )

  def is_mode_supported(self):
     if self.mode in self.modes.keys():
         return True
     return False
 
  def get_mode_cfg(self):
     try:
       return self.modes[self.mode]
     except KeyError:
       return {}


  def mode_changed(self, entity, attribute, old, new, kwargs):
     self.log("Mode changed: {}".format(new))

     self.mode = new

     if self.on_handle:
        self.cancel_listen_state(self.on_handle)
     if self.off_handle:
        self.cancel_listen_state(self.off_handle)
        self.off_handle = None

     if self.is_mode_supported():
        self.on_handle = self.listen_state(self.motion_on, 
          self.args['motion_detector'], new="on", old="off")
        if self.light == "on":
          self.turn_light_on() # change color
     else:
        self.log("mode change - light off")
        self.turn_light_off()

  def luminosity_changed(self, entity, attribute, old, new, kwargs):
     self.log("Luminosity changed: {}".format(new))
     self.luminosity = float(new)
     self.update()

  def motion_on(self, entity, attribute, old, new, kwargs):
     self.log("Motion on")
     self.update()

  def motion_off(self, entity, attribute, old, new, kwargs):
     self.log("Motion off")
     self.turn_light_off()

  def light_on(self, entity, attribute, old, new, kwargs):
     self.log("Light on")
     self.light = new

  def light_off(self, entity, attribute, old, new, kwargs):
     self.log("Light off")
     self.light = new
     self.disarm_off_trigger()

  def update(self):
     self.log("update (mode: {}, luminosity: {}, off: {}, cfg: {})".format(
              self.mode, self.luminosity, self.off_handle, self.get_mode_cfg()))
     if self.is_mode_supported():
       self.log("update: mode OK")
       cfg = self.get_mode_cfg()
       motion = self.get_state(self.args['motion_detector'])
       if motion == "on":
          self.log("update: motion OK")
          if self.luminosity < cfg.luminosity:
             self.log("update: luminosity OK")
             if self.light == "off":
                self.log("update: light OK")
                self.turn_light_on()
                self.rearm_off_trigger()
                return
          if self.off_handle:
             self.rearm_off_trigger()
     self.log("update: end")

  def turn_light_on(self):
     cfg = self.get_mode_cfg()
     self.log("turning light on (color {})".format(cfg.color))
     self.turn_on(self.args['light'], rgb_color=cfg.color)
     #force the color with buggy lights
     self.turn_on(self.args['light'], rgb_color=cfg.color)

  def disarm_off_trigger(self):
     if self.off_handle:
          self.cancel_listen_state(self.off_handle)
          self.log("off trigger disarmed")

  def rearm_off_trigger(self):
     cfg = self.get_mode_cfg()
     self.disarm_off_trigger()
     self.off_handle = self.listen_state(self.motion_off, 
          self.args['motion_detector'], 
          new="off", duration=cfg.off_timeout)
     #TODO: seems that self.cancel_listen_state doesn't work as expeced
     # the motion_off is sometimes called even if there have been
     # motion_on's in between, we need to utilize some noonce usages
     # or something to prevent the light from being turned off if the
     # call back have been made obsolete in between.
     self.log("Off trigger armed: (timeout: {})".format(cfg.off_timeout))

  def turn_light_off(self):
     self.log("turning light off")
     self.cancel_listen_state(self.off_handle)
     self.off_handle = None
     self.turn_off(self.args['light'])
