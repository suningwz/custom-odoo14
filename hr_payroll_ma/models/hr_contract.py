# -*- encoding: utf-8 -*-

from odoo import api, fields, models

class hr_contract(models.Model):
    _inherit = "hr.contract"
    
    @api.onchange('state')
    def _onchange_state(self):
        if self.state != 'open':
            self.actif = False
        else:
            self.actif = True