# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
import time
import base64
from odoo.exceptions import except_orm, Warning, RedirectWarning, ValidationError

class HrPayrollVariable(models.Model):
    _name = 'hr.payroll.variable'
    _description = 'Saisi des variable'
    
    name = fields.Char(default='Interface de saisie des variables')
    hr_rubrique_id = fields.Many2one(comodel_name='hr.payroll_ma.rubrique', string="Rubrique", required=True)
    period_id = fields.Many2one('date.range', domain="[('type_id.fiscal_period','=',True)]", string=u'Période', required=True)
    global_amount = fields.Float(string='Montant générique')
    hr_payroll_variable_line_ids = fields.One2many(comodel_name='hr.payroll.variable.line', inverse_name='hr_payroll_variable_id', string="Rubrique")
    hr_department_ids = fields.Many2many(comodel_name='hr.department', string="Départements")
    hr_job_ids = fields.Many2many(comodel_name='hr.job', string="Titres de postes")
    filter_type = fields.Selection([
        ('all', 'Tous'),
        ('per_employee', 'Employé'),
        ('per_department', 'Département'),
        ('per_job', 'Titre de poste')
    ], string=u'Critère de sélection', required=True, default='per_employee') 
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('in_progress', 'En cours de saisie'),
        ('done', 'Terminée'),
        ('cancel', 'Annulée')
    ], string=u'Etat', required=True, default='draft')
    
    file_content = fields.Binary(string='Import File')
    
    def action_in_progress(self):
        self.state = 'in_progress'
        
    def action_done(self):
        HrPayrollMaLigneRubrique = self.env['hr.payroll_ma.ligne_rubrique']
        for variable_line in self.hr_payroll_variable_line_ids:
            amount = 0
            if self.hr_rubrique_id.amount_number == 'amount':
                amount = variable_line.amount
            else:
                if self.hr_rubrique_id.day_hour == 'daily':
                    amount = variable_line.number * self.hr_rubrique_id.coefficient * (variable_line.contract_id.wage / 26)
                else:
                    amount = variable_line.number * self.hr_rubrique_id.coefficient * (variable_line.contract_id.wage / 191)
            
            if not variable_line.hr_payroll_ma_ligne_rubrique_id:
                payroll_rubrique_line_values = {
                                                'rubrique_id': self.hr_rubrique_id.id,
                                                'montant': amount,
                                                'taux': 100,
                                                'id_contract': variable_line.contract_id.id,
                                                'period_id': self.period_id.id,
                                                'date_start': self.period_id.date_start,
                                                'date_stop': self.period_id.date_end
                                                }
                variable_line.write({'hr_payroll_ma_ligne_rubrique_id': HrPayrollMaLigneRubrique.create(payroll_rubrique_line_values).id})
            else:
                variable_line.hr_payroll_ma_ligne_rubrique_id.write({'rubrique_id': self.hr_rubrique_id.id,
                                                'montant': amount,
                                                'taux': 100,
                                                'id_contract': variable_line.contract_id.id,
                                                'period_id': self.period_id.id,
                                                'date_start': self.period_id.date_start,
                                                'date_stop': self.period_id.date_end})
        self.state = 'done'
        
    def action_cancel(self):
        for variable_line in self.hr_payroll_variable_line_ids:
            for rubrique_line in variable_line.contract_id.rubrique_ids:
                if rubrique_line.rubrique_id==self.hr_rubrique_id:
                    rubrique_line.unlink()
        self.state = 'cancel'

    def unlink(self):
        for variable_line in self.hr_payroll_variable_line_ids:
            for rubrique_line in variable_line.contract_id.rubrique_ids:
                if rubrique_line.rubrique_id==self.hr_rubrique_id:
                    rubrique_line.unlink()
        
    def action_reset(self):
        self.state = 'draft'
    
    def filter_confirm(self):
        HrPayrollVariableLine = self.env['hr.payroll.variable.line']
        HrContract = self.env['hr.contract']
        
        existing_contracts = [line.contract_id for line in self.mapped("hr_payroll_variable_line_ids")]
        
        if self.filter_type == 'all':
            contracts = HrContract.search([('actif', '=', True)])
        if self.filter_type == 'per_department':
            contracts = HrContract.search([('department_id', 'in', self.hr_department_ids.ids), ('actif', '=', True)])
        if self.filter_type == 'per_job':
            contracts = HrContract.search([('job_id', 'in', self.hr_job_ids.ids), ('actif', '=', True)])
        
        for contract in contracts - set(existing_contracts):
            payroll_variable_line_values = {
                                            'employee_id': contract.employee_id.id,
                                            'contract_id': contract.id,
                                            'hr_payroll_variable_id': self.id
                                            }
            HrPayrollVariableLine.create(payroll_variable_line_values)
    
    def set_global_amount(self):
        for variable_line in self.hr_payroll_variable_line_ids:
            variable_line.write({'amount': self.global_amount})

    def import_file(self):
        for record in self:
            HrContract = self.env['hr.contract']
            if not record.file_content:
                    raise exceptions.except_orm(('Erreur!'), ("Veuillez indiquer le fichier CSV !"))
            file_content = record.file_content
            file_content_binary = base64.decodestring(file_content)
            file_content_binary = file_content_binary.decode("ISO-8859-1")
            if file_content_binary:
                file_content_reader = file_content_binary.split('\n')
                data = {}
                i = 0
                for row in file_content_reader:
                    i += 1
                    if i == 1:
                        continue
                    line = row.split(';')
                    if len(line) == 1:
                        continue
                    empty_row = True
                    for l in line:
                        if l.strip():
                            empty_row = False
                            break
                    if empty_row:
                        continue
                    employee_id = self.env['hr.employee'].search([('name','=',line[0])])
                    if not employee_id:
                        raise ValidationError(u'Aucun employé portant le matricule %s (ligne %s)'% (line[0], i))
                    
                    data["employee_id"] = employee_id[0].id
                    contracts = HrContract.search([('employee_id', '=', employee_id[0].id), ('actif', '=', True)])
                    if not contracts:
                        raise ValidationError(u'%s n\'a aucun contrat'% (line[0]))
                    
                    data["contract_id"] = contracts[0].id
                    data["number"] = line[1]
                    data["amount"] = line[2]
                    data["hr_payroll_variable_id"] = record.id
                    self.env['hr.payroll.variable.line'].create(data)
                    data = {}
        return True

class HrPayrollVariableLine(models.Model):
    _name = 'hr.payroll.variable.line'
    
    employee_id = fields.Many2one(comodel_name='hr.employee', string="Employé", required=True)
    contract_id = fields.Many2one(comodel_name='hr.contract', string="Contrat", required=True)
    hr_payroll_ma_ligne_rubrique_id = fields.Many2one(comodel_name='hr.payroll_ma.ligne_rubrique', string="Ligne")
    number = fields.Float(string="Nombre")
    amount = fields.Float(string="Montant")
    hr_payroll_variable_id = fields.Many2one(comodel_name='hr.payroll.variable', string="Saisie variable")
    
    @api.onchange('employee_id')
    def onchange_employee_id(self):
        HrContract = self.env['hr.contract']
        contracts = HrContract.search([('employee_id', '=', self.employee_id.id), ('actif', '=', True)])
        if contracts:
            self.contract_id = contracts[0].id
        