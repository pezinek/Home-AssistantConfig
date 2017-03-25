import appdaemon.appapi as appapi

#
# SmoothLight
#
# Will listen to controll events and smoothly adjust color of selected light
#
# Args:
#   light: light to controll
#
# Example event:
#
# Event Type: desired_color
# Data: {"rgb_color": [255,128,0]}

class RGBColor(object):
    def __init__(self, r=0, g=0, b=0):
        self.r = self.g = self.b = float(0)
        self.update([r,g,b])

    def __str__(self):
        #return "RGBColor #%02X%02X%02X" % (self.r, self.g, self.b)
        return "RGBColor (%f,%f,%f)" % (self.r, self.g, self.b)

    def __sub__(self, other):
        return RGBColor(self.r-other.r, self.g-other.g, self.b-other.b)

    def __add__(self, other):
        return RGBColor(self.r+other.r, self.g+other.g, self.b+other.b)

    def __truediv__(self, other):
        return RGBColor(self.r/other, self.g/other, self.b/other)

    def __mul__(self, other):
        return RGBColor(self.r*other, self.g*other, self.b*other)

    def __abs__(self):
        return abs(self.r) + abs(self.g) + abs(self.b)

    def update(self, rgb_list):
        self.r = float(rgb_list[0])
        self.g = float(rgb_list[1])
        self.b = float(rgb_list[2])

        return self

    def transition(self, ammount, desired_color, logger):
        
        diff = desired_color - self

        diff_sum = abs(diff)

        if diff_sum < ammount:
           ammount = diff_sum

        ratio = diff / diff_sum
        change = ratio * ammount

        return self + change

    def as_list(self):
        return [self.r, self.g, self.b]


class SmoothLight(appapi.AppDaemon):

  def initialize(self):
     self.cur_color = RGBColor(0,0,0)
     self.desired_color = None
     self.ammount = 18 
     self.period = 0 

     self.listen_state(self.light_off, self.args['light'], new="off")
     self.listen_event(self.light_event, "state_changed", entity_id=self.args['light'])
     self.listen_event(self.controll_event, "desired_color", entity_id=self.args['light'])

     self.log("SmootLight init complete")

  def transition_in_progress(self):
     if self.desired_color is not None:
        if (abs(self.cur_color - self.desired_color) > 0):
           return True
     return False

  def stop_transition(self):
     self.desired_color = None

  def light_off(self, entity, attribute, old, new, kwargs):
     self.stop_transition()
     self.cur_color = RGBColor(0,0,0)

  def light_event(self, event_name, data, kwargs):
     if self.transition_in_progress():
           return

     try:
        self.cur_color.update(data['new_state']['attributes']['rgb_color'])
        self.log("Color changed: %s" % self.cur_color)
        self.update({})
     except KeyError:
        #self.log("no color info present")
        pass

  def controll_event(self, event_name, data, kwargs):
     try:
        self.desired_color=RGBColor().update(data['rgb_color'])
        self.log("New desired color: %s" % self.desired_color)
        try:
            self.ammount = abs(self.desired_color - self.cur_color)/data['time']
            self.log("New ammount: %s" % self.ammount)  
        except KeyError:
            pass

        self.update({})
     except KeyError:
        pass

  def update(self, kwargs):

     if self.transition_in_progress():
         #self.log("Cur color: %s" % self.cur_color)
         new_color = self.cur_color.transition(self.ammount, self.desired_color, self)
         if abs(new_color) == 0:
            self.log("Light off")
            self.turn_off(self.args['light'])
         else:
            self.log("Color set: %s" % new_color)
            self.turn_on(self.args['light'], rgb_color=new_color.as_list())

         self.cur_color = new_color
         self.run_in(self.update, self.period)
     else:
         self.stop_transition()

