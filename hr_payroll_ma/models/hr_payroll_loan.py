# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
import time
from odoo.exceptions import except_orm, Warning, RedirectWarning

class HrPayrollLoan(models.Model):
    _name = 'hr.payroll.loan'
    _description = 'Tableau d\'amortissement'
    
    name = fields.Char(default='Interface de saisie des variables')
    employee_id = fields.Many2one(comodel_name='hr.employee', string="Employé", required=True)
    loan_amount = fields.Float(string='Montant du prêt')
    hr_payroll_loan_line_ids = fields.One2many(comodel_name='hr.payroll.loan.line', inverse_name='hr_payroll_loan_id', string="Rubrique")

class HrPayrollLoanLine(models.Model):
    _name = 'hr.payroll.loan.line'
    
    employee_id = fields.Many2one(related='hr_payroll_loan_id.employee_id', string="Employé", required=True)
    period_id = fields.Many2one('date.range', domain="[('type_id.fiscal_period','=',True)]", string=u'Période', required=True)
    principal_amount = fields.Float(string="Principal")
    interet_amount = fields.Float(string="Montant intérêt")
    hr_payroll_loan_id = fields.Many2one(comodel_name='hr.payroll.loan', string="Tableau d'amortissement")
