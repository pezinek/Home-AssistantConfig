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

class ModeSettings(object):
  def __init__(self, luminosity, off_timeout, color):
        self.luminosity = luminosity
        self.off_timeout = off_timeout
        self.color = color

  def __repr__(self):
        return str(self.__dict__)


class MoodyMotionTrigger(appapi.AppDaemon):

  def initialize(self):

     self.log("Init started")

     self.on_handle = None
     self.off_handle = None
     self.luminosity = None
     self.mode = None

     self._load_modes()

     lum = self.get_state(self.args['luminosity_sensor'])
     self.luminosity_changed(self.args['luminosity_sensor'], None, lum, lum, {})
     self.listen_state(self.luminosity_changed, self.args['luminosity_sensor'])

     mode = self.get_state(self.args['mode_selector'])
     self.mode_changed(self.args['mode_selector'], None, mode, mode, {})
     self.listen_state(self.mode_changed, self.args['mode_selector'])




     self.log("Init complete: (modes: {})".format(self.modes))

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
        cfg = self.modes[self.mode]
        self.on_handle = self.listen_state(self.motion_on, 
          self.args['motion_detector'], 
          new="on", color=cfg.color, luminosity=cfg.luminosity)
     self.update()

  def luminosity_changed(self, entity, attribute, old, new, kwargs):
     self.log("Luminosity changed: {}".format(new))
     self.luminosity = float(new)
     self.update()

  def motion_on(self, entity, attribute, old, new, kwargs):
     self.log("Motion on")
     self.update()

  def motion_off(self, entity, attribute, old, new, kwargs):
     self.log("Motion off")
     self.cancel_listen_state(self.off_handle)
     self.off_handle = None
     self.log("light off - no motion")
     self.turn_off(self.args['light'])

  def update(self):
     self.log("update (mode: {}, luminosity: {}, off: {}, cfg: {})".format(
              self.mode, self.luminosity, self.off_handle, self.get_mode_cfg()))
     if self.is_mode_supported():
       cfg = self.get_mode_cfg()
       if self.luminosity < cfg.luminosity:
          motion = self.get_state(self.args['motion_detector'])
          if motion == "on":
                self.log("light on (color {})".format(cfg.color))
                self.turn_on(self.args['light'], rgb_color=cfg.color)
        
                if self.off_handle:
                    self.cancel_listen_state(self.off_handle)
                self.off_handle = self.listen_state(self.motion_off, 
                    self.args['motion_detector'], 
                    new="off", duration=cfg.off_timeout)

