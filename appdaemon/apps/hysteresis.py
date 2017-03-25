import appdaemon.appapi as appapi

#
# Hysteresis
#
# Will convert numeric value of a sensor to discrete states of a switch.
# If numeric value of a <sensor> would be lower than <low> for at least <lowtime>
# service <lowsvc> will be called on the <switch> entity. 
# Similarly if <sensor> value would be higher than <high> for at least <hightime> 
# service <highsvc> will be called on the <switch>.
#
# Args:
#   switch: switch to turn on and off
#   sensor: sensor to monitor
#   low:      low sensor value  
#   lowtime:  time in seconds for which sensor needs to be bellow <low> 
#             (default: 0)
#   lowsvc:   service to call on the switch when sensor is <low> for <lowtime>
#             (default: 'homeassistant.turn_on')
#   high:     hight sensor value
#   hightime: time in seconds for which sensor needs to be above <high>
#             (default: 0)
#   highsvc:  state to turn the switch to when sensor is <high> for <hightime>
#             (default: 'homeassistant.turn_off')
#

class Hysteresis(appapi.AppDaemon):

  def initialize(self):
        self.log("Initialize")
        self.timer = None
        self.listen_state(self.sensor_changed, self.args['sensor'])
        self.listen_event(self.ha_started, "ha_started")
        self.fetch_sensor()

  def fetch_sensor(self):
        val = self.get_state(self.args['sensor'])
        if val is not None:
            self.sensor_changed(self.args['sensor'], 'state', val, val, {})

  def ha_started(self, event_name, data, kwargs):
        self.fetch_sensor()

  def sensor_changed(self, entity, attribute, old, new, kwargs):
        self.log("New senosor value: %s (old %s)" % (new, old))

        new = float(new)
        old = float(old)
        high = float(self.args['high'])
        low = float(self.args['low'])

        if (
            ((old > high) != (new > high)) or 
            ((old < low) != (new < low)) or
            ((new > low) and (new < high))
        ):
                if self.timer:
                        self.log("Timer canceled - value crossed boundaries")
                        self.cancel_timer(self.timer)
                        self.timer = None

        if (new > high) and (self.timer is None):
                s = self.args['highsvc']
                t = self.args['hightime']
                self.log("High timer scheduled: %s s (%s > %s)" % (t,new,high))
                self.timer = self.run_in(self.update_switch, t, svc=s)

        if (new < low) and (self.timer is None):
                s = self.args['lowsvc']
                t = self.args['lowtime']
                self.log("Low timer scheduled: %s s (%s < %s)" % (t,new,low))
                self.timer = self.run_in(self.update_switch, t, svc=s)


  def update_switch(self, kwargs):
        self.log("Timer fired: %s -> %s" % (kwargs['svc'], self.args['switch']))
        self.call_service(kwargs['svc'], entity_id = self.args['switch'])
        self.timer = None

