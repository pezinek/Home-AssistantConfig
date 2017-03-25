import appdaemon.appapi as appapi

# Args:
#  selector: input_select that will be controlled
#  options: list of options to support
#
# for each option we then require following args:
#
#  <option>_entity: entity to monitor for status changes
#  <option>_state:  state that will turn on the mode

class SelectController(appapi.AppDaemon):

  def initialize(self):

    for opt in self.args['options'].split():
      self.listen_state(self.entity_changed, 
                        self.args['%s_entity' % opt],
                        constrain_state=self.args['%s_state' % opt],
                        opt=opt)

  def entity_changed(self, entity, attribute, old, new, kwargs):
	
    if new == kwargs['constrain_state']:	
      self.log("input_select.select_option: entity=%s option=%s" % (entity, kwargs['opt']))
      self.call_service("input_select/select_option", 
                        entity_id=self.args['selector'],
                        option=kwargs['opt'])


