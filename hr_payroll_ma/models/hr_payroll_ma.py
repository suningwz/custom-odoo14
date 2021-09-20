# -*- encoding: utf-8 -*-

from odoo import api, fields, models
import time
from . import convertion
import datetime
from odoo.exceptions import ValidationError, UserError
from dateutil.relativedelta import *
import logging
_logger = logging.getLogger(__name__)

# Classe : Paie
class hr_payroll_ma(models.Model):

    @api.model
    def create(self,vals):
        date_debut = self.env['date.range'].browse(int(vals['period_id'])).date_start
        new_date = date_debut + relativedelta(months=-1)
        previous_period_id = self.env['date.range'].search([('date_start','=',new_date),('type_id.fiscal_period', '=', True)])

        id_payroll = super(hr_payroll_ma,self).create(vals)
        return id_payroll

    @api.model
    def _get_journal(self):
            journal_obj = self.env['account.journal']
            res = journal_obj.search( [('name', '=', 'journal des salaires')], limit=1)
            if res:
                return res[0].id
            else:
                return False


    @api.model
    def _get_currency(self):
            currency_obj = self.env['res.currency']
            res = currency_obj.search([('name', '=', 'MAD')], limit=1)
            if res:
                return res[0].id
            else:
                return False

    @api.model
    def _get_partner(self):

            company_obj = self.env['res.company']
            ids_company=company_obj.search([])

            if ids_company[0].partner_id:
                return ids_company[0].partner_id.id
            else:
                return False

    @api.model
    def _name_get_default(self):
            return self.env['ir.sequence'].next_by_code('hr.payroll_ma')

    def get_total_net(self):
        for rec in self:
            net=0
            for line in rec.bulletin_line_ids:
                net+=line.salaire_net_a_payer

            rec.total_net = net
    
    _name = "hr.payroll_ma"
    _description = 'Saisie des bulletins'
    _order = "number"


    name = fields.Char(string='Description', size=256)
    number = fields.Char(string=u'Numéro du salaire', size=256,default=_name_get_default, readonly=True)
    date_start = fields.Date(string=u'Date début')
    date_end = fields.Date(string=u'Date fin')
    date_salary = fields.Date(string='Date salaire', states={'open':[('readonly', True)], 'close':[('readonly', True)]})
    partner_id = fields.Many2one('res.partner',default=_get_partner, string='Employeur',   required=True, states={'draft':[('readonly', False)]})
    period_id = fields.Many2one('date.range', string=u'Période', domain=[('type_id.fiscal_period', '=', True)],  required=True, states={'draft':[('readonly', False)]})
    bulletin_line_ids = fields.One2many('hr.payroll_ma.bulletin', 'id_payroll_ma', string='Bulletins',  states={'draft':[('readonly', False)]})
    move_id = fields.Many2one('account.move', string='Pièce comptable', readonly=True, help="Link to the automatically generated account moves.")
    currency_id = fields.Many2one('res.currency',default=_get_currency, string='Devise', required=True,  states={'draft':[('readonly', False)]})
    journal_id = fields.Many2one('account.journal',default=_get_journal, string='Journal', required=True,  states={'draft':[('readonly', False)]})
    state = fields.Selection([('draft', 'Draft'),
            ('confirmed', u'Confirmé'),
            ('paid', 'Done'),
            ('cancelled', 'Cancelled')], string='State', select=2, readonly=True,default='draft')
    total_net = fields.Float(string='Total net', compute='get_total_net', digits=(16, 2))
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Société',
        required=True,
        default=lambda self: self.env['res.company']._company_default_get(),
        states={'draft':[('readonly', False)]}
    )
    @api.constrains('period_id', 'partner_id')
    def _check_unicity_periode(self):

            payroll_ids = self.env['hr.payroll_ma'].search([('period_id','=',self.period_id.id), ('partner_id','=',self.partner_id.id)])
            if len(payroll_ids) > 1 :
                raise ValidationError(u'On ne peut pas avoir deux paies pour la même période, pour la même unité!!!')
            return True

    def unlink(self):

        for rec in self:

            if rec.state != 'draft':
                raise ValidationError(u"Suppression impossible")

            rec.bulletin_line_ids.unlink()
            payroll_id = super(hr_payroll_ma,self).unlink()
            return payroll_id


    @api.onchange('partner_id','period_id')
    def onchange_period_id(self):
        if self.partner_id and self.period_id:
            self.name = 'Paie '+ self.partner_id.name + ' de la periode ' + self.period_id.name
            self.date_start = self.period_id.date_start
            self.date_end = self.period_id.date_end


    def draft_cb(self):

        for rec in self:
            if rec.move_id:
                raise ValidationError(u"Veuillez d'abord supprimer les écritures comptables associés")

            rec.state = 'draft'


    def confirm_cb(self):
        for rec in self:
            ''' Skip Generating JE '''
            rec.action_move_create()
            rec.state = 'confirmed'
    def cancel_cb(self):
        for rec in self:
            rec.state = 'cancelled'


    def generate_employees(self):

        for rec in self:
            employees = self.env['hr.employee']
            obj_contract = self.env['hr.contract']

            emp = employees.search([('active','=',True),('date','<=',rec.date_end),('company_id','=',rec.company_id.id)])

            line={}
            if rec.state == 'draft':
                sql = '''
                DELETE from hr_payroll_ma_bulletin where id_payroll_ma = %s
                    '''
                self.env.cr.execute(sql,(rec.id,))


            for e in emp :
                contract_ids = obj_contract.search([('employee_id','=',e.id), ('actif', '=', True)], order='date_start')
                employe = employees.browse(e['id'])
                if contract_ids and employe.company_id == rec.partner_id.company_id:
                    contract = contract_ids[-1:][0]
                    number_days_not_working = 0
                    number_days_not_working = sum(leave.number_of_days for leave in self.env['hr.leave'].search([('employee_id','=',e.id), 
                                                                                                                     ('state','=','validate'),
                                                                                                                     ('holiday_status_id.code', '=', 'IMP'), 
                                                                                                                     ('date_from','>=',rec.date_start),
                                                                                                                     ('date_from','<=',rec.date_end)]))
                    line = {
                            'employee_id' : e.id,
                            'employee_contract_id' : contract.id,
                            'working_days':26 - number_days_not_working,
                            'normal_hours' : contract.monthly_hour_number,
                            'hour_base' : contract.hour_salary,
                            'salaire_base' : contract.wage,
                            'id_payroll_ma': rec.id,
                            'period_id':rec.period_id.id,
                            'date_start':rec.date_start ,
                            'date_end':rec.date_end,
                    }
                    self.env['hr.payroll_ma.bulletin'].create(line)
                
        return True

    def compute_all_lines(self):
        for sal in self:

            bulletins = self.env['hr.payroll_ma.bulletin'].search([('id_payroll_ma','=',sal.id)])

            for bul in bulletins:
                bul.compute_all_lines()
        return True

    #Generation des écriture comptable
    def action_move_create(self):
        for rec in self:
            params = self.env['hr.payroll_ma.parametres']
            dictionnaire = params.search([('company_id','=',rec.company_id.id)])


            company_currency = rec.currency_id.id

            # one move line per salary period
            date = rec.date_salary or time.strftime('%Y-%m-%d')
            partner = rec.partner_id.id

            journal = rec.journal_id

            """
            if journal.centralisation:
                raise ValidationError(u"Cannot create salary move on centralised journal")
            """

            period_id = rec.period_id and rec.period_id or False
            if not period_id:
                raise ValidationError(u"Période obligatoire !!!")


            move = {}
            move_lines = []
            bulletins=self.env['hr.payroll_ma.bulletin'].search([('id_payroll_ma','=',rec.id)])

            bulletins_query_cond=str(tuple(bulletins.ids))
            '''if tuple(bulletins).__len__() == 1:
                #string = str(tuple(bulletins)).remove(',')
                bulletins_query_cond='('+str(bulletins[0].id)+')'''
            '''else:
                bulletins_query_cond = '('
                for b in bulletins:
                    bulletins_query_cond += str(b.id) + ','

                bulletins_query_cond =  bulletins_query_cond[:-1] +')'''''
            
            print (bulletins_query_cond)


            sql='''
                    SELECT l.name as name , sum(subtotal_employee) as subtotal_employee,sum(subtotal_employer) as           subtotal_employer,l.credit_account_id,l.debit_account_id
                    FROM hr_payroll_ma_bulletin_line l
                    LEFT JOIN account_account aa ON aa.id=l.credit_account_id
                    RIGHT JOIN account_account ab ON ab.id=l.debit_account_id
                    where l.type = 'cotisation' and id_bulletin in %s
                    group by l.name,l.credit_account_id,l.debit_account_id
                    '''% (bulletins_query_cond)

            self.env.cr.execute(sql)
            data=self.env.cr.dictfetchall()
            #def action_move_create2(self, cr, uid, ids):

            for line in data :
                if line['subtotal_employee'] :
                            #=======================================================
                            # move_line_debit={
                            #             'account_id' : sal.employee_contract_id.salary_debit_account_id.id,
                            #             'period_id' : period_id,
                            #             'journal_id' : journal_id,
                            #             'date' : date,
                            #             'name' : (line.name or '\\' )+ ' Salarial',
                            #             'debit' : line.subtotal_employee,
                            #             'partner_id' : line.partner_id and line.partner_id.id,
                            #             'currency_id': company_currency,
                            #             }
                            #=======================================================
                    move_line_credit = {
                                         'account_id' : line['credit_account_id'],
                                         #'period_id' : period_id.id,

                                         'journal_id' : journal.id,
                                         'date' : date,
                                         'name' : (line['name'] or '\\') + ' Salarial',
                                         'credit' : line['subtotal_employee'] if line['subtotal_employee'] > 0 else 0,
                                         'debit' : (-1 * line['subtotal_employee']) if line['subtotal_employee'] < 0 else 0,
                                         'partner_id' : partner,
                                         #'currency_id': company_currency,
                                         #'state' : 'valid'
                                         }
                            #move_lines.append((0,0,move_line_debit))
                    move_lines.append((0, 0, move_line_credit))


                if line['subtotal_employer'] :
                        move_line_debit = {
                                         'account_id' : line['debit_account_id'],
                                         #'period_id' : period_id.id,

                                         'journal_id' : journal.id,
                                         'date' : date,
                                         'name' : (line['name'] or '\\') + ' Patronal',
                                         'debit' : line['subtotal_employer'] if line['subtotal_employer'] > 0 else 0,
                                         'credit' :(-1 * line['subtotal_employer']) if line['subtotal_employer'] < 0 else 0,
                                         'partner_id' : partner,
                                         #'currency_id': company_currency,
                                         #'state' : 'valid'
                                         }
                        move_line_credit = {
                                         'account_id' : line['credit_account_id'],
                                         #'period_id' : period_id.id,

                                         'journal_id' : journal.id,
                                         'date' : date,
                                         'name' : (line['name'] or '\\') + ' Patronal',
                                         'debit' : (-1 * line['subtotal_employer']) if line['subtotal_employer'] < 0 else 0,
                                         'credit' : line['subtotal_employer'] if line['subtotal_employer'] > 0 else 0,
                                         'partner_id' : partner,
                                         #'currency_id': company_currency,
                                         #'state' : 'valid'
                                         }
                        move_lines.append((0, 0, move_line_debit))
                        move_lines.append((0, 0, move_line_credit))



            sql='''
                    SELECT sum(salaire_brute) as salaire_brute,sum(salaire_net_a_payer) as salaire_net_a_payer,sum(arrondi) as arrondi,sum(deduction) as deduction
                    FROM hr_payroll_ma_bulletin b
                    LEFT JOIN hr_payroll_ma pm ON pm.id=b.id_payroll_ma
                    where b.id_payroll_ma = %s
                    '''% (rec.id)
            self.env.cr.execute(sql)
            data=self.env.cr.dictfetchall()
            data = data[0]
            """
            move_line_debit = {
                                         'account_id' : dictionnaire.salary_debit_account_id.id,
                                         #'analytic_account_id': dictionnaire['analytic_account_id'][0],
                                         'period_id' : period_id.id,
                                         'journal_id' : journal.id,
                                         'date' : date,
                                         'name' : 'Salaire Brute',
                                         'debit' :  data['salaire_brute']-data['deduction'],
                                         'credit' : 0,
                                         'partner_id' : partner,
                                         #'currency_id': company_currency,
                                         'state' : 'valid'
                                         }
            """
            # On effectue le split entre le salaire de base + ancienneté et les rubriques de paie
            sql='''
                    SELECT l.name as name , sum(subtotal_employee) as subtotal_employee,sum(subtotal_employer) as           subtotal_employer,l.credit_account_id,l.debit_account_id
                    FROM hr_payroll_ma_bulletin_line l
                    LEFT JOIN account_account aa ON aa.id=l.credit_account_id
                    RIGHT JOIN account_account ab ON ab.id=l.debit_account_id
                    where l.type = 'brute' and id_bulletin in %s
                    group by l.name,l.credit_account_id,l.debit_account_id
                    '''% (bulletins_query_cond)

            self.env.cr.execute(sql)
            data_rub=self.env.cr.dictfetchall()
            #def action_move_create2(self, cr, uid, ids):
            for line in data_rub :
                
                if line['debit_account_id']:
                    move_line_debit_rubrique = {
                                             'account_id' : line['debit_account_id'],
                                             #'analytic_account_id': dictionnaire['analytic_account_id'][0],
                                             #'period_id' : period_id.id,
    
                                             'journal_id' : journal.id,
                                             'date' : date,
                                             'name' : line['name'] or '\\',
                                             'debit' :  line['subtotal_employee'] if line['subtotal_employee'] > 0 else 0,
                                             'credit' : (-1 * line['subtotal_employee']) if line['subtotal_employee'] < 0 else 0,
                                             'partner_id' : partner,
                                             #'currency_id': company_currency,
                                             #'state' : 'valid'
                                             }
                    move_lines.append((0, 0, move_line_debit_rubrique))
                print ("AUTRES "),move_line_debit_rubrique

            
            
            # Retenu
            sql='''
                    SELECT l.name as name , sum(subtotal_employee) as subtotal_employee,sum(subtotal_employer) as           subtotal_employer,l.credit_account_id,l.debit_account_id
                    FROM hr_payroll_ma_bulletin_line l
                    where l.type = 'retenu' and id_bulletin in %s
                    group by l.name,l.credit_account_id,l.debit_account_id
                    '''% (bulletins_query_cond)

            self.env.cr.execute(sql)
            data_rub=self.env.cr.dictfetchall()
            print (data_rub)
            #def action_move_create2(self, cr, uid, ids):
            for line in data_rub :
                
                if line['debit_account_id']:
                    move_line_debit_rubrique = {
                                             'account_id' : line['debit_account_id'],
                                             #'analytic_account_id': dictionnaire['analytic_account_id'][0],
                                             #'period_id' : period_id.id,
    
                                             'journal_id' : journal.id,
                                             'date' : date,
                                             'name' : line['name'] or '\\',
                                             'debit' :  line['subtotal_employee'] if line['subtotal_employee'] > 0 else 0,
                                             'credit' : (-1 * line['subtotal_employee']) if line['subtotal_employee'] < 0 else 0,
                                             'partner_id' : partner,
                                             #'currency_id': company_currency,
                                             #'state' : 'valid'
                                             }
                    move_lines.append((0, 0, move_line_debit_rubrique))
                    
                if line['credit_account_id']:
                    move_line_credit_rubrique = {
                                             'account_id' : line['credit_account_id'],
                                             #'analytic_account_id': dictionnaire['analytic_account_id'][0],
                                             #'period_id' : period_id.id,
    
                                             'journal_id' : journal.id,
                                             'date' : date,
                                             'name' : line['name'] or '\\',
                                             'debit' :  (-1 * line['subtotal_employee']) if line['subtotal_employee'] < 0 else 0,
                                             'credit' : line['subtotal_employee'] if line['subtotal_employee'] > 0 else 0,
                                             'partner_id' : partner,
                                             #'currency_id': company_currency,
                                             #'state' : 'valid'
                                             }
                    move_lines.append((0, 0, move_line_credit_rubrique))

            sql='''
                    SELECT  sum(subtotal_employee) as subtotal_employee,sum(subtotal_employer) as           subtotal_employer,l.credit_account_id,l.debit_account_id
                    FROM hr_payroll_ma_bulletin_line l
                    where l.type = 'brute' and id_bulletin in %s
                    and l.credit_account_id is null and l.debit_account_id is null
                    group by l.credit_account_id,l.debit_account_id
                    '''% (bulletins_query_cond)

            self.env.cr.execute(sql)
            data_paie=self.env.cr.dictfetchall()
            #def action_move_create2(self, cr, uid, ids):
            for line in data_paie :
                move_line_debit_brute = {
                                         'account_id' : dictionnaire.salary_debit_account_id.id,
                                         #'analytic_account_id': dictionnaire['analytic_account_id'][0],
                                         #'period_id' : period_id.id,
                                         'journal_id' : journal.id,
                                         'date' : date,
                                         'name' : 'Salaire brute',
                                         'debit' :  line['subtotal_employee'] if line['subtotal_employee'] > 0 else 0,
                                         'credit' : (-1 * line['subtotal_employee']) if line['subtotal_employee'] < 0 else 0,
                                         'partner_id' : partner,
                                         #'currency_id': company_currency,
                                         #'state' : 'valid'
                                         }
                move_lines.append((0, 0, move_line_debit_brute))


            move_line_arrondi = {
                                         'account_id' : dictionnaire.salary_debit_account_id.id,
                                         #'analytic_account_id': dictionnaire['analytic_account_id'][0],
                                         #'period_id' : period_id.id,
                                         'journal_id' : journal.id,
                                         'date' : date,
                                         'name' : 'Arrondi',
                                         'debit' :  data['arrondi'],
                                         'credit' : 0,
                                         'partner_id' : partner,
                                         #'currency_id': company_currency,
                                         #'state' : 'valid'
                                         }
            move_line_credit = {
                                         'account_id' : dictionnaire.salary_credit_account_id.id,
                                         #'period_id' : period_id.id,
                                         'journal_id' : journal.id,
                                         'date' : date,
                                         'name' : 'Salaire net a payer',
                                         'credit' : data['salaire_net_a_payer'],
                                         'debit' : 0,
                                         'partner_id' : partner,
                                         #'currency_id': company_currency,
                                         #'state' : 'valid'
                                         }
            #move_lines.append((0, 0, move_line_debit))
            move_lines.append((0, 0, move_line_arrondi))
            move_lines.append((0, 0, move_line_credit))


            c=0
            d=0
            for e in move_lines:

                c +=  e[2]['credit'] if e[2]['credit'] else 0
                d +=  e[2]['debit'] if e[2]['debit'] else 0


            print ('CREDIT GLOBAL =') , c, round(c,1)
            print ('DEBIT GLOBAL =') , d, round(d,1)

            if c < d:
                diff = d-c
                move_line_arrondi = {
                                         'account_id' : dictionnaire.salary_debit_account_id.id,
                                         #'analytic_account_id': dictionnaire['analytic_account_id'][0],
                                         #'period_id' : period_id.id,
                                         'journal_id' : journal.id,
                                         'date' : date,
                                         'name' : 'Arrondi significatif généré suite à un désequilibre (A analyser)',
                                         'credit' :  round(diff,2),
                                         'debit' : 0,
                                         'partner_id' : partner,
                                         #'currency_id': company_currency,
                                         #'state' : 'valid'
                                         }
                move_lines.append((0, 0, move_line_arrondi))
            else:
                diff = c-d
                move_line_arrondi = {
                                         'account_id' : dictionnaire.salary_debit_account_id.id,
                                         #'analytic_account_id': dictionnaire['analytic_account_id'][0],
                                         #'period_id' : period_id.id,
                                         'journal_id' : journal.id,
                                         'date' : date,
                                         'name' : 'Arrondi',
                                         'debit' :  round(diff,2),
                                         'credit' : 0,
                                         'partner_id' : partner,
                                         #'currency_id': company_currency,
                                         #'state' : 'valid'
                                         }
                move_lines.append((0, 0, move_line_arrondi))



            move = {'ref': rec.number,
                      #'period_id' : period_id.id,
                      'journal_id' : journal.id,
                      'date' : date,
                      'state' : 'draft',
                      'name' : '/',
                      'line_ids' : move_lines}
            #print "move",move
            move_id = self.env['account.move'].create(move)
            rec.move_id = move_id

            return True


# Classe : Bulletin de paie
class hr_payroll_ma_bulletin(models.Model):
    _name = "hr.payroll_ma.bulletin"
    _description = 'bulletin'
    _order = "name"

    @api.depends('salaire_net_a_payer')
    def _get_amount_text(self):

        for rec in self:
            devise= 'Dirham'
            rec.salaire_net_a_payer_text = convertion.trad(rec.salaire_net_a_payer,devise).upper()


    @api.model
    def _name_get_default(self):
        return self.env['ir.sequence'].next_by_code('hr.payroll_ma.bulletin')

    name = fields.Char(string=u'Numéro du salaire', size=128, readonly=True,default=_name_get_default)
    date_start = fields.Date(string=u'Date début')
    date_end = fields.Date(string='Date fin')
    date_salary = fields.Date(string='Date salaire')
    employee_id = fields.Many2one('hr.employee', string=u'Employé', required=True)
    period_id = fields.Many2one('date.range', domain="[('type_id.fiscal_period','=',True)]", string=u'Période')
    salary_line_ids = fields.One2many('hr.payroll_ma.bulletin.line', 'id_bulletin', string='lignes de salaire', readonly=True)
    employee_contract_id = fields.Many2one('hr.contract', string=u'Contrat de travail', required=True)
    id_payroll_ma = fields.Many2one('hr.payroll_ma', string=u'Réf Salaire', ondelete='cascade')
    salaire_base = fields.Float(string='Salaire de base')
    taux_journalier = fields.Float(string='Taux journalier')
    normal_hours = fields.Float(string=u'Heures travaillée durant le mois')
    hour_base = fields.Float(string=u'Salaire heure')
    comment=fields.Text(string=u'Informations complémentaires')
    salaire = fields.Float(string='Salaire Base', readonly=True, digits=(16, 2))
    salaire_brute = fields.Float(string='Salaire Brute', readonly=True, digits=(16, 2))
    salaire_brute_imposable = fields.Float(string='Salaire brute imposable', readonly=True, digits=(16, 2))
    '''MO'''
    salaire_brute_imposable_ir = fields.Float(string='Salaire brute imposable IR', readonly=True, digits=(16, 2))
    ''''''
    salaire_net = fields.Float(string=u'Salaire Net', readonly=True, digits=(16, 2))
    salaire_net_a_payer = fields.Float(string=u'Salaire Net à payer', readonly=True, digits=(16, 2))
    indemnites_frais_pro = fields.Float(string=u'Indemnités versées à titre de frais professionnels', readonly=True, digits=(16, 2))
    salaire_net_a_payer_text = fields.Char(compute='_get_amount_text', string='Montant en lettre',
          store=True,
          help="Montant en lettre.")
    salaire_net_imposable = fields.Float(string=u'Salaire Net Imposable', readonly=True, digits=(16, 2))
    cotisations_employee = fields.Float(string=u'Cotisations Employé', readonly=True, digits=(16, 2))
    cotisations_employer = fields.Float(string='Cotisations Employeur', readonly=True, digits=(16, 2))
    igr = fields.Float(string=u'Impot sur le revenu', readonly=True, digits=(16, 2))
    prime = fields.Float(string='Primes', readonly=True, digits=(16, 2))
    indemnite = fields.Float(string=u'Indémnités', readonly=True, digits=(16, 2))
    avantage = fields.Float(string='Avantages', readonly=True, digits=(16, 2))
    exoneration = fields.Float(string=u'Exonérations', readonly=True, digits=(16, 2))
    deduction = fields.Float(string=u'Déductions', readonly=True, digits=(16, 2))
    working_days = fields.Float(string=u'Jours travaillés', size=64, digits=(16, 2))
    prime_anciennete = fields.Float(string=u'Prime ancienneté', size=64, digits=(16, 2))
    frais_pro = fields.Float(string='Frais professionnels', size=64, digits=(16, 2))
    personnes = fields.Integer(string='Personnes')
    absence =fields.Float(string='Absences', size=64, digits=(16, 2))
    arrondi = fields.Float(string='Arrondi', size=64, digits=(16, 2))
    logement = fields.Float(string='Logement', size=64, digits=(16, 2))

    # Ajout des champs de cumul
    cumul_work_days=fields.Float(compute='get_cumuls', string=u'Cumul Jrs travaillés', digits=(16, 2))
    cumul_sbi= fields.Float(compute='get_cumuls', string='Cumul SBI', digits=(16, 2))
    '''MO'''
    cumul_sbir= fields.Float(compute='get_cumuls', string='Cumul SBIR', digits=(16, 2))
    ''''''
    cumul_sb= fields.Float(compute='get_cumuls', string='Cumul SB', digits=(16, 2))
    cumul_sbi_n_1 = fields.Float(compute='get_cumuls_n_1', string='Cumul SBI N-1', digits=(16, 2))
    cumul_sni= fields.Float(compute='get_cumuls', string='Cumul SNI', digits=(16, 2))
    cumul_sni_n_1= fields.Float(compute='get_cumuls_n_1', string=u'Cumul SNI N-1', digits=(16, 2))
    cumul_igr= fields.Float(compute='get_cumuls', string='Cumul IR', digits=(16, 2))
    cumul_igr_n_1= fields.Float(compute='get_cumuls_n_1', string='Cumul IR N-1', digits=(16, 2))
    cumul_ee_cotis = fields.Float(compute='get_cumuls', string=u'Cumul Cotis employé', digits=(16, 2))
    cumul_ee_cotis_n_1 = fields.Float(compute='get_cumuls_n_1', string=u'Cumul Cotis employé N-1', digits=(16, 2))
    cumul_er_cotis = fields.Float(compute='get_cumuls', string='Cumul Cotis employeur', digits=(16, 2))
    cumul_fp = fields.Float(compute='get_cumuls', string='Cumul frais professionnels', digits=(16, 2))
    cumul_avn = fields.Float(compute='get_cumuls', string=u'Cumul Avg en nature', digits=(16, 2))
    cumul_exo = fields.Float(compute='get_cumuls', string=u'Cumul exonéré', digits=(16, 2))
    cumul_indemnites_fp = fields.Float(compute='get_cumuls', string='Cumul Ind. frais professionnels')

    

    def get_bulletin_cumuls(self,mois, annee, employe):

        ligne_bul_paie = self.env['hr.payroll_ma.bulletin.line']
        acct_period = self.env['date.range']
        bul = self.env['hr.payroll_ma.bulletin']
        cumuls = {}

        for res in self:
            v_period = str(mois).rjust(2,'0') + "/" + str(annee)
            period = acct_period.search([('name','=',v_period)])
            bulletin = bul.search([('period_id','=',period.id),('employee_id','=',employe)])

            if bulletin:
                bul = bulletin[0]
                cumuls['working_days'] = bul.working_days
                cumuls['salaire_brut_imposable'] = bul.salaire_brute_imposable
                cumuls['salaire_brut'] = bul.salaire_brute
                cumuls['salaire_net_imposable'] = bul.salaire_net_imposable
                cumuls['igr'] = bul.igr
                '''MO'''
                cumuls['salaire_brute_imposable_ir'] = bul.salaire_brute_imposable_ir
                cumuls['cotisations_employee'] = bul.cotisations_employee
                cumuls['cotisations_employer'] = bul.cotisations_employer
                cumuls['indemnites_frais_pro'] = bul.indemnites_frais_pro
                cumuls['exonerations'] = bul.exoneration
                cumuls['avn'] = bul.indemnite
                if bul.frais_pro < 2500:
                    cumuls['fp'] = bul.frais_pro
                else:
                    cumuls['fp'] = 2500.0


        return cumuls

    def get_cumuls(self):

            i = 1

            for res in self:

                periode = res.period_id.name.split('/')

                mois = periode[0]
                annee = periode[1]

                somme_wd = 0.0
                somme_sbi = 0.0
                somme_sb = 0.0
                somme_sni = 0.0
                somme_igr = 0.0
                somme_cot_ee = 0.0
                somme_cot_er = 0.0
                somme_fp = 0.0
                somme_avn = 0.0
                somme_ind_fp = 0.0
                somme_exo = 0.0
                somme_sbir = 0.0
                
                for j in range(1,int(mois)+1,1):


                    valeur_mois = res.get_bulletin_cumuls(j,annee,res.employee_id.id)

                    if valeur_mois:

                        somme_wd += valeur_mois['working_days']
                        somme_sbi += valeur_mois['salaire_brut_imposable']
                        somme_sb += valeur_mois['salaire_brut']
                        somme_sni += valeur_mois['salaire_net_imposable']
                        somme_igr += valeur_mois['igr']
                        somme_cot_ee += valeur_mois['cotisations_employee']
                        somme_cot_er += valeur_mois['cotisations_employer']
                        somme_fp += valeur_mois['fp']
                        somme_avn += valeur_mois['avn']
                        somme_ind_fp += valeur_mois['indemnites_frais_pro']
                        somme_exo += valeur_mois['exonerations']
                        '''MO'''
                        somme_sbir += valeur_mois['salaire_brute_imposable_ir']
                        ''''''


                res.cumul_work_days = somme_wd
                res.cumul_sbi = somme_sbi
                '''MO'''
                res.cumul_sbir = somme_sbir
                ''''''
                res.cumul_sb = somme_sb
                res.cumul_sni = somme_sni
                res.cumul_igr = somme_igr
                res.cumul_ee_cotis = somme_cot_ee
                res.cumul_er_cotis = somme_cot_er
                res.cumul_fp = somme_fp
                res.cumul_avn = somme_avn
                res.cumul_indemnites_fp = somme_ind_fp
                res.cumul_exo = somme_exo


    def get_cumuls_n_1(self):

            i=1

            for res in self:

                periode = res.period_id.name.split('/')

                mois = periode[0]
                annee = periode[1]

                somme_sbi = 0.0
                somme_cotisation_ee = 0.0
                somme_sni = 0.0
                somme_igr = 0.0

                for j in range(1,int(mois),1):


                    valeur_mois = res.get_bulletin_cumuls(j,annee,res.employee_id.id)

                    if valeur_mois:

                        somme_sbi += valeur_mois['salaire_brut_imposable']
                        somme_cotisation_ee += valeur_mois['cotisations_employee']
                        somme_sni += valeur_mois['salaire_net_imposable']
                        somme_igr += valeur_mois['igr']
                
                res.cumul_sbi_n_1 = somme_sbi
                res.cumul_ee_cotis_n_1 = somme_cotisation_ee
                res.cumul_sni_n_1 = somme_sni
                res.cumul_igr_n_1 = somme_igr
                


    @api.model
    def _name_get_default(self):
         return self.env['ir.sequence'].next_by_code('hr.payroll_ma.bulletin')


    @api.onchange('employee_contract_id')
    def onchange_contract_id(self):
        for rec in self:

            contract = rec.employee_contract_id
            salaire_base = 0
            normal_hours = 0
            hour_base = 0

            if contract:
                rec.salaire_base = contract.wage
                rec.hour_base = contract.hour_salary
                rec.normal_hours = contract.monthly_hour_number
                rec.employee_id = contract.employee_id.id

            else:
                rec.salaire_base = salaire_base
                rec.hour_base = normal_hours
                rec.normal_hours = hour_base



    @api.onchange('employee_id')
    def onchange_employee_id(self):

        for rec in self:

            employee_contract_id = False
            partner_id = False
            date_begin = time.strftime('%Y-%m-%d'),
            salaire_base = 0
            normal_hours = 0
            hour_base = 0
            days=0

            if not rec.period_id:
                raise ValidationError(u"Vous devez d\'abord spécifier une période !")

            if rec.period_id and rec.employee_id :

                if not rec.employee_id.contract_id:
                    return {}
                else:
                    sql = '''select sum(number_of_days) from hr_holidays h
                        left join hr_holidays_status s on (h.holiday_status_id=s.id)
                        where date_from >= '%s' and date_to <= '%s'
                        and employee_id = %s
                        and state = 'validate'
                        and s.payed=False''' % (rec.period_id.date_start, rec.period_id.date_end, rec.employee_id.id)
                    self.env.cr.execute(sql)
                    res = self.env.cr.fetchone()
                    if res[0] == None:
                        days = 0
                    else :
                        days = res[0]

                    #for contract in employee.contract_ids :
                    #    if date_begin and contract.date_start <= date_begin and \
                    #    (contract.date_end and contract.date_end >= date_begin or not contract.date_end) :
                    #        employee_contract_id = contract.id
                    #        salaire_base = contract.wage
                    #        hour_base = contract.hour_salary
                    #        normal_hours = contract.monthly_hour_number


                    rec.employee_contract_id = rec.employee_id.contract_id.id
                    rec.salaire_base =  rec.employee_id.contract_id.wage
                    rec.hour_base = rec.employee_id.contract_id.hour_salary
                    rec.normal_hours = rec.employee_id.contract_id.monthly_hour_number
                    rec.working_days = 26 - abs(days)
                    rec.period_id = rec.period_id.id
    

    
    #La fonction pour le calcul du taux de la prime d'anciennete
    def get_prime_anciennete(self):

        for rec in self:

            bulletin = rec
            date_salary = bulletin.period_id.date_end
            date_embauche = bulletin.employee_id.date

            if bulletin.employee_id.anciennete:
                date_salary = str(date_salary)
                date_salary = date_salary.split('-')
                date_embauche = str(date_embauche)
                date_embauche = date_embauche.split('-')
                jours1 = 0
                jours2 = 0

                jours1 = ((int(date_salary[0]) * 365) + (int(date_salary[1]) * 30) + int((date_salary[2])))
                jours2 = ((int(date_embauche[0]) * 365) + (int(date_embauche[1]) * 30) + (int(date_embauche[2])))

                if date_salary[1] in ['01','03','05','07','08','10']:
                    jours2+=1

                anciennete = (jours1 - jours2) / 365

                objet_anciennete = self.env['hr.payroll_ma.anciennete']
                liste = objet_anciennete.search([])

                for tranche in liste:
                    if anciennete < 0:
                        taux = 0.0
                    else:
                        if(anciennete >= tranche.debuttranche) and (anciennete < tranche.fintranche):
                            taux = tranche.taux

                return taux
            else:
                return 0.0


    ####La fonction pour la calcul de IGR
    def get_igr(self, montant,rubriques, cotisations):

        for rec in self:

            res = {}
            taux=0
            somme=0
            salaire_net_imposable = 0
            bulletin = rec
            params = self.env['hr.payroll_ma.parametres']
            ids_params = params.search([('company_id','=',rec.id_payroll_ma.company_id.id)])

            # On extrait le numéro de la période en cours
            period = bulletin.period_id.name
            code_mois=0
            if period:
                code_mois = int(period.split('/')[0])

            base_calcul_ir = bulletin.cumul_sni
            base_ir_actuelle = bulletin.cumul_sni


            #salaire_net_imposable = bulletin.salaire_net_imposable
            dictionnaire = ids_params[0]

            if not bulletin.employee_contract_id.ir:
                """
                rec.salaire_net_imposable = salaire_net_imposable
                rec.taux = 0
                rec.ir_net = 0
                rec.credit_account_id = dictionnaire.credit_account_id.id
                rec.frais_pro = 0
                rec.personnes = 0
                """

                res = {'salaire_net_imposable':salaire_net_imposable,
                     'taux':0,
                     'ir_net':0,
                     'credit_account_id':dictionnaire.credit_account_id.id,
                     'frais_pro' : 0,
                     'personnes' : 0
                     }

            else:
                personnes = bulletin.employee_id.chargefam
                logement = bulletin.employee_id.logement
                fraispro = montant * dictionnaire.fraispro / 100
                if fraispro < dictionnaire.plafond:
                    salaire_net_imposable = montant - fraispro - cotisations
                else :
                    salaire_net_imposable = montant - dictionnaire.plafond - cotisations


                # On vérifie la règle de rabattement de l'IR
                #mt_interets = bulletin.employee_id.logement
                mt_interets = self.env['hr.payroll.loan.line'].search([('employee_id','=',bulletin.employee_id.id), ('period_id', '=', bulletin.period_id.id)], limit=1).interet_amount if self.env['hr.payroll.loan.line'].search([('employee_id','=',bulletin.employee_id.id), ('period_id', '=', bulletin.period_id.id)], limit=1) else 0
                type_logement = bulletin.employee_id.type_logement
                if mt_interets > 0:
                    mt_rabattement = 0
                    if type_logement == 'social' and bulletin.employee_contract_id.wage <= dictionnaire.salaire_max_logement_social:
                        mt_rabattement = mt_interets
                    else:
                        mt_rabattement = min(salaire_net_imposable*0.1,mt_interets)
                    salaire_net_imposable -= mt_rabattement

                objet_ir = self.env['hr.payroll_ma.ir']
                liste = objet_ir.search([])

                base_calcul_ir = 0
                base_calcul_ir = bulletin.cumul_sni_n_1 + salaire_net_imposable
                ratio = (312/bulletin.cumul_work_days or 1)

                for tranche in liste:
                    if(base_calcul_ir * (312/bulletin.cumul_work_days or 1) >= tranche.debuttranche) and (base_calcul_ir * (312/bulletin.cumul_work_days or 1) < tranche.fintranche):
                        taux = tranche.taux
                        somme = tranche.somme
                  
                #ir_brute = (salaire_net_imposable * taux / 100) - somme
                ir_brute = (base_calcul_ir * (312/bulletin.cumul_work_days) * taux / 100) - somme
                ir_brute *= (bulletin.cumul_work_days/312)
                ir_brute -= bulletin.cumul_igr_n_1
                
                if((ir_brute - (personnes * dictionnaire.charge)) < 0):
                    ir_net = 0
                else:
                    ir_net = ir_brute - (personnes * dictionnaire.charge)

                """
                rec.salaire_net_imposable = salaire_net_imposable
                rec.taux = taux
                rec.ir_net = ir_net
                rec.credit_account_id = dictionnaire.credit_account_id.id
                rec.frais_pro = fraispro
                rec.personnes = personnes
                """
                res = {'salaire_net_imposable':salaire_net_imposable,
                 'taux':taux,
                 'ir_net':ir_net,
                 'credit_account_id':dictionnaire.credit_account_id.id,
                 'frais_pro' : fraispro,
                 'personnes' : personnes,
                 }

        return res
    
    def get_igr_2(self, montant,rubriques, cotisations, css=False):

        for rec in self:

            res = {}
            taux=0
            somme=0
            salaire_net_imposable = 0
            bulletin = rec
            params = self.env['hr.payroll_ma.parametres']
            ids_params = params.search([('company_id','=',rec.id_payroll_ma.company_id.id)])

            # On extrait le numéro de la période en cours
            period = bulletin.period_id.name
            code_mois=0
            if period:
                code_mois = int(period.split('/')[0])

            base_calcul_ir = bulletin.cumul_sni
            base_ir_actuelle = bulletin.cumul_sni


            #salaire_net_imposable = bulletin.salaire_net_imposable
            dictionnaire = ids_params[0]

            if not bulletin.employee_contract_id.ir:
                """
                rec.salaire_net_imposable = salaire_net_imposable
                rec.taux = 0
                rec.ir_net = 0
                rec.credit_account_id = dictionnaire.credit_account_id.id
                rec.frais_pro = 0
                rec.personnes = 0
                """

                res = {'salaire_net_imposable':salaire_net_imposable,
                     'taux':0,
                     'ir_net':0,
                     'credit_account_id':dictionnaire.credit_account_id.id,
                     'frais_pro' : 0,
                     'personnes' : 0
                     }

            else:
                personnes = bulletin.employee_id.chargefam
                logement = bulletin.employee_id.logement
                fraispro = montant * dictionnaire.fraispro / 100
                frais_pro_reelle = 0
                if fraispro < dictionnaire.plafond:
                    frais_pro_reelle = fraispro
                    salaire_net_imposable = montant - fraispro - cotisations
                else :
                    frais_pro_reelle = dictionnaire.plafond
                    salaire_net_imposable = montant - dictionnaire.plafond - cotisations
                _logger.warning('Amine 1 %s %s %s %s %s' % (salaire_net_imposable, montant, cotisations,fraispro, dictionnaire.plafond ))

                # On vérifie la règle de rabattement de l'IR
                mt_interets = self.env['hr.payroll.loan.line'].search([('employee_id','=',bulletin.employee_id.id), ('period_id', '=', bulletin.period_id.id)], limit=1).interet_amount if self.env['hr.payroll.loan.line'].search([('employee_id','=',bulletin.employee_id.id), ('period_id', '=', bulletin.period_id.id)], limit=1) else 0
                type_logement = bulletin.employee_id.type_logement
                mt_rabattement = 0
                if mt_interets > 0:
                    mt_rabattement = 0
                    if type_logement == 'social' and bulletin.employee_contract_id.wage <= dictionnaire.salaire_max_logement_social:
                        mt_rabattement = mt_interets
                    else:
                        mt_rabattement = min(salaire_net_imposable*0.1,mt_interets)
                    salaire_net_imposable -= mt_rabattement if css == False else 0
                
                objet_ir = self.env['hr.payroll_ma.ir']
                liste = objet_ir.search([])

                base_calcul_ir = 0
                base_calcul_ir = bulletin.cumul_sni_n_1 + salaire_net_imposable
                ratio = (312/bulletin.cumul_work_days if bulletin.cumul_work_days else 1)
                
                for tranche in liste:
                    if(base_calcul_ir * (312/bulletin.cumul_work_days if bulletin.cumul_work_days else 1) >= (tranche.debuttranche) and (base_calcul_ir * (312/bulletin.cumul_work_days if bulletin.cumul_work_days else 1) < (tranche.fintranche))):
                        taux = tranche.taux
                        somme = tranche.somme
                _logger.warning('SN1 %s %s %s %s' % (mt_rabattement, base_calcul_ir, ratio, base_calcul_ir *(26/bulletin.cumul_work_days if bulletin.cumul_work_days else 1)))
                _logger.warning('SN2 %s %s' % (taux, somme))
                ir_brute = (base_calcul_ir * (312/bulletin.cumul_work_days if bulletin.cumul_work_days else 1) * taux / 100) - somme
                _logger.warning('IR1 %s' % (ir_brute))
                
                if((ir_brute - (personnes * dictionnaire.charge)) < 0):
                    ir_brute = 0
                else:
                    ir_brute = ir_brute - (personnes * dictionnaire.charge * 12)


                """ir_brute = (base_calcul_ir * (312/bulletin.cumul_work_days or 1) * taux / 100) - somme"""
                '''ir_brute = ir_brute * (bulletin.cumul_work_days/312 or 1) - cumul_igr_n_1'''
                '''if((ir_brute - (personnes * dictionnaire.charge)) < 0):
                    ir_brute = 0
                else:
                    ir_brute = ir_brute - (personnes * dictionnaire.charge)'''
                _logger.warning('IR2 %s' % (ir_brute))
                ir_brute *= (bulletin.cumul_work_days/312)
                _logger.warning('IR3 %s' % (ir_brute))
                ir_brute -= bulletin.cumul_igr_n_1
                _logger.warning('IR4 %s' % (ir_brute))
                
                if(ir_brute < 0):
                    ir_brute = 0
                else:
                    ir_brute = ir_brute
                
                """
                rec.salaire_net_imposable = salaire_net_imposable
                rec.taux = taux
                rec.ir_net = ir_net
                rec.credit_account_id = dictionnaire.credit_account_id.id
                rec.frais_pro = fraispro
                rec.personnes = personnes
                """
                res = {'salaire_net_imposable':salaire_net_imposable,
                 'taux':taux,
                 'ir_net':ir_brute,
                 'credit_account_id':dictionnaire.credit_account_id.id,
                 'frais_pro' : fraispro,
                 'frais_pro_reelle': frais_pro_reelle,
                 'personnes' : personnes,
                 'mt_rabattement' : mt_rabattement
                 }

        return res

    def compute_all_lines(self):

        for rec in self:

            params = self.env['hr.payroll_ma.parametres']
            dictionnaire = params.search([('company_id','=',rec.id_payroll_ma.company_id.id)])
            id_bulletin = rec.id

            bulletin = rec
            rec.period_id = bulletin.id_payroll_ma.period_id.id

            sql = '''
            DELETE from hr_payroll_ma_bulletin_line where id_bulletin = %s
            '''
            self.env.cr.execute(sql, (id_bulletin,))
            salaire_base = bulletin.salaire_base
            e_taux_journalier = bulletin.taux_journalier
            normal_hours = bulletin.normal_hours
            normal_hours_old=0
            hour_base = bulletin.hour_base
            working_days = bulletin.working_days

            salaire_brute = 0
            salaire_brute_imposable = 0
            salaire_net = 0
            salaire_net_imposable = 0
            cotisations_employee = 0
            cotisations_employer = 0
            cotisations_employee_ir = 0
            prime = 0
            indemnite = 0
            avantage = 0
            exoneration = 0
            prime_anciennete = 0
            deduction = 0
            logement = 0
            frais_pro = 0
            personne = 0
            absence = 0
            arrondi=0
            donnees_pointage={}

            # On vérifie si on a des heures supplémentaires
            rub_hsup_25 = self.env.ref('hr_payroll_ma.hsup_25')
            rub_hsup_50 = self.env.ref('hr_payroll_ma.hsup_50')
            rub_hsup_100 = self.env.ref('hr_payroll_ma.hsup_100')

            if salaire_base :
                absence += salaire_base - (salaire_base * (bulletin.working_days / 26))

                salaire_base_line = {
                    'name' : 'Salaire de base', 'id_bulletin' : id_bulletin, 'type' : 'brute','base' : round(salaire_base,2),
                    'rate_employee' : round((bulletin.working_days / 26) * 100,2), 'subtotal_employee':round(salaire_base * (bulletin.working_days / 26),2),'deductible' : False,
                   }
                salaire_brute += salaire_base * (bulletin.working_days / 26)

                self.env['hr.payroll_ma.bulletin.line'].create(salaire_base_line)

            if hour_base :

                normale_hours_line = {
                    'name' : 'Heures normales', 'id_bulletin' : id_bulletin, 'type' : 'brute','base' : normal_hours,
                    'rate_employee' : hour_base, 'subtotal_employee':normal_hours * hour_base,'deductible' : False,
                    }
                salaire_brute += hour_base * round(normal_hours,2)

                self.env['hr.payroll_ma.bulletin.line'].create(normale_hours_line)

            salaire_brute_imposable = salaire_brute
            sql = '''
            SELECT l.montant,l.taux,r.name,r.categorie,r.type,r.formule,r.afficher,r.sequence,r.imposable,r.plafond,r.plafond_ir,r.ir,r.anciennete,r.absence,r.id,r.conge,r.credit_account_id, r.debit_account_id
            FROM hr_payroll_ma_ligne_rubrique l
            LEFT JOIN hr_payroll_ma_rubrique r on (l.rubrique_id=r.id)
            WHERE
            ((l.id_contract=%s and l.permanent=True) OR
            (l.id_contract=%s and l.date_start <= %s and l.date_stop >= %s))
            AND
            r.id not in (%s,%s,%s) AND r.company_id = %s
            order by r.sequence
            '''
            self.env.cr.execute(sql, (bulletin.employee_contract_id.id, bulletin.employee_contract_id.id, bulletin.period_id.date_start, bulletin.period_id.date_start,rub_hsup_25.id,rub_hsup_50.id,rub_hsup_100.id,bulletin.employee_contract_id.company_id.id))
            rubriques = self.env.cr.dictfetchall()
            ir = salaire_brute_imposable
            
            anciennete = 0
            for rubrique in rubriques :
                print (rubrique)
                
                print (type(rubrique['plafond_ir']), type(rubrique['plafond']))
                if(rubrique['categorie'] == 'majoration'):
                    if rubrique['formule'] :
                        try:
                            rubrique['montant'] = eval(str(rubrique['formule']))
                        except Exception as e:
                            raise ValidationError("Erreur !")


                    # actualisation montant jours chômés payés & jours congés payés
                    taux = rubrique['taux']
                    montant = rubrique['montant']

                    if rubrique['conge']:
                        taux = rubrique['taux']
                        montant = 0


                    if rubrique['absence'] and not rubrique['conge']:
                        taux = bulletin.working_days / 26
                        montant = rubrique['montant'] * taux
                        taux=taux * 100
                        absence += rubrique['montant'] - montant
                    if rubrique['anciennete']  and not rubrique['conge'] : anciennete += montant
                    if rubrique['ir']:
                        if rubrique['plafond_ir'] == 0:ir += montant
                        elif montant <= rubrique['plafond_ir']:
                            ecart = rubrique['montant'] - rubrique['plafond_ir']
                            ir += ecart * (rec.working_days / 26 if rubrique['absence'] else 1) if ecart > 0 else 0
                        elif montant > rubrique['plafond_ir']:
                            '''if rubrique['plafond_ir']:
                                ir += montant - rubrique['plafond_ir']
                            else:
                                ir += montant'''
                            ir += montant - rubrique['plafond_ir'] * (rec.working_days / 26 if rubrique['absence'] else 1)
                    
                    '''if not rubrique['imposable']  and not rubrique['conge']:
                        if rubrique['plafond'] == 0:
                            exoneration += montant
                        elif montant <= rubrique['plafond']:
                            exoneration += montant
                        elif montant > rubrique['plafond']:
                            exoneration += rubrique['plafond']
                            salaire_brute_imposable += montant - rubrique['plafond']'''
                            
                    self.env['hr.payroll_ma.imposition.rubrique'].search([('rubrique_id', '=', rubrique['id'])])
                    
                    if rubrique['type'] == 'prime'  and not rubrique['conge']:
                            prime += montant
                    elif rubrique['type'] == 'indemnite'  and not rubrique['conge']:
                            indemnite += montant
                    elif rubrique['type'] == 'avantage'  and not rubrique['conge']:
                            avantage += montant

                    majoration_line = {
                    'name' : rubrique['name'], 'id_bulletin' : id_bulletin, 'type' : 'brute','base' : rubrique['montant'],
                     'rate_employee' : taux , 'subtotal_employee':montant, 'deductible' : False,'afficher' : rubrique['afficher'],
                        'credit_account_id':rubrique['credit_account_id'] or False, 'debit_account_id':rubrique['debit_account_id'] or False
                        }

                    self.env['hr.payroll_ma.bulletin.line'].create(majoration_line)

            # On insère les heures supplémentaires

            sql_hsup = '''
            SELECT l.montant,l.taux,r.name,r.categorie,r.type,r.formule,r.afficher,r.sequence,r.imposable,r.plafond,r.plafond_ir,r.ir,r.anciennete,r.absence,r.id,r.conge,r.credit_account_id, r.debit_account_id
            FROM hr_payroll_ma_ligne_rubrique l
            LEFT JOIN hr_payroll_ma_rubrique r on (l.rubrique_id=r.id)
            WHERE
            ((l.id_contract=%s and l.permanent=True) OR
            (l.id_contract=%s and l.date_start <= %s and l.date_stop >= %s))
            AND
            r.id in (%s,%s,%s) AND r.company_id = %s
            order by r.sequence
            '''
            self.env.cr.execute(sql_hsup, (bulletin.employee_contract_id.id, bulletin.employee_contract_id.id, bulletin.period_id.date_start, bulletin.period_id.date_start,rub_hsup_25.id,rub_hsup_50.id,rub_hsup_100.id,bulletin.employee_contract_id.company_id.id))
            rubriques_hsup = self.env.cr.dictfetchall()

            for rubrique in rubriques_hsup :

                if(rubrique['categorie'] == 'majoration'):

                    # actualisation montant jours chômés payés & jours congés payés
                    taux = rubrique['taux']
                    montant = rubrique['montant']

                    if bulletin.employee_contract_id.monthly_hour_number > 0:
                        taux_horaire = bulletin.salaire_base / bulletin.employee_contract_id.monthly_hour_number or 1
                    else:
                        taux_horaire = bulletin.salaire_base / 192

                    montant = taux_horaire * taux

                    if rubrique['conge']:
                        taux = rubrique['taux']
                        montant = 0

                    print (rubrique)
                    if rubrique['ir']:
                        if rubrique['plafond_ir']:
                            if rubrique['plafond_ir'] == 0:ir += montant
                            elif montant <= rubrique['plafond_ir']:
                                ir += montant
                            elif montant > rubrique['plafond_ir']:
                                ir += montant - rubrique['plafond_ir'] * (rec.working_days / 26 if rubrique['absence'] else 1)
                        else:
                            ir += montant
                            
                    if not rubrique['imposable']  and not rubrique['conge']:
                        if rubrique['plafond'] == 0:
                            exoneration += montant
                        elif montant <= rubrique['plafond']:
                            exoneration += montant
                        elif montant > rubrique['plafond']:
                            exoneration += rubrique['plafond']
                            salaire_brute_imposable += montant - rubrique['plafond']
                            
                    if rubrique['type'] == 'prime'  and not rubrique['conge']:
                            prime += montant
                    elif rubrique['type'] == 'indemnite'  and not rubrique['conge']:
                            indemnite += montant
                    elif rubrique['type'] == 'avantage'  and not rubrique['conge']:
                            avantage += montant

                    majoration_line = {
                    'name' : rubrique['name'], 'id_bulletin' : id_bulletin, 'type' : 'brute','base' : taux_horaire,
                     'rate_employee' : taux , 'subtotal_employee':montant, 'deductible' : False,'afficher' : rubrique['afficher'],
                        'credit_account_id':rubrique['credit_account_id'] or False, 'debit_account_id':rubrique['debit_account_id'] or False
                        }

                    self.env['hr.payroll_ma.bulletin.line'].create(majoration_line)


            
            # ancienneté
            taux_anciennete = self.get_prime_anciennete() / 100
            prime_anciennete = (salaire_brute + anciennete) * taux_anciennete
            if taux_anciennete :
                anciennete_line = {
                    'name' : 'Prime anciennete', 'id_bulletin' : id_bulletin,'type' : 'brute',
                    'base' : (salaire_brute + anciennete), 'rate_employee' : taux_anciennete, 'subtotal_employee':prime_anciennete,
                    'deductible' : False,
                    }
                self.env['hr.payroll_ma.bulletin.line'].create(anciennete_line)
            
            base_cotisation_golbal = salaire_brute + prime_anciennete
            salaire_brute += prime + indemnite + avantage + prime_anciennete
            salaire_brute_imposable=salaire_brute-exoneration
            cotisations = bulletin.employee_contract_id.cotisation.cotisation_ids
            base=0
            if bulletin.employee_id.affilie:
                for cot in cotisations :
                    base_cotisation = base_cotisation_golbal
                    
                    ''' PART Cotisation '''
                    for rubrique_dict in rubriques:
                        rubrique = self.env['hr.payroll_ma.rubrique'].browse(rubrique_dict['id'])
                        imposition_ids = rubrique.mapped('imposition_ids').filtered(lambda r: r.imposition_id.id == cot.id)
                        for imposition in imposition_ids:
                            if imposition.plafonne:
                                if imposition.plafond_mt < rubrique_dict['montant']:
                                    base_cotisation += (rubrique_dict['montant'] * (bulletin.working_days / 26 if rubrique.absence else 1) - imposition.plafond_mt * (bulletin.working_days / 26 if rubrique.absence else 1))
                            else:
                                base_cotisation += rubrique_dict['montant'] * (bulletin.working_days / 26 if rubrique.absence else 1)
                            
                    if cot.plafonee and base_cotisation >= cot.plafond:
                        base_cotisation = cot.plafond
                    
                    salaire_brute_imposable = base_cotisation
                    
                    absence_ratio_pp = 1
                    absence_ratio_ps = 1
                    
                    if cot.absence_pp:
                        absence_ratio_pp = bulletin.working_days / 26
                    if cot.absence_ps:
                        absence_ratio_ps = bulletin.working_days / 26
                    
                    part_patronal = 0
                    part_salarial = 0
                    
                    if cot.type == 'calculated':
                        if cot.base_contract == True:
                            sql='''
                                SELECT %s
                                FROM hr_contract
                                where employee_id = %s
                            '''% (cot.technical_name_patronal,bulletin.employee_id.id)
                            self.env.cr.execute(sql)
                            data = self.env.cr.dictfetchall()
                            part_patronal = (data[0][cot.technical_name_patronal] or 0 ) * absence_ratio_pp
                            
                            sql='''
                                SELECT %s
                                FROM hr_contract
                                where employee_id = %s
                            '''% (cot.technical_name_salarial,bulletin.employee_id.id)
                            self.env.cr.execute(sql)
                            data = self.env.cr.dictfetchall()
                            part_salarial = (data[0][cot.technical_name_salarial] or 0 ) * absence_ratio_ps
                        else:
                            part_patronal = base_cotisation * cot.tauxpatronal / 100 * absence_ratio_pp
                            part_salarial = base_cotisation * cot.tauxsalarial / 100 * absence_ratio_ps
                    else:
                        part_patronal = cot.amount_patronal
                        part_salarial = cot.amount_salarial
                            
                    cotisation_line = {
                                       'name' : cot.name,'id_bulletin' : id_bulletin,'type' : 'cotisation','base' : base_cotisation,
                                       'rate_employee' : cot.tauxsalarial,'rate_employer' : cot.tauxpatronal * absence_ratio_pp,
                                       'subtotal_employee': part_salarial,
                                       'subtotal_employer': part_patronal,
                                       'credit_account_id': cot.credit_account_id.id,
                                       'debit_account_id' : cot.debit_account_id.id,
                                       'deductible' : True,
                    }
                    cotisations_employee += part_salarial
                    cotisations_employer += part_patronal
                    cotisations_employee_ir += part_salarial if cot.ir == True else 0
                    self.env['hr.payroll_ma.bulletin.line'].create(cotisation_line)

                ###############Import sur le revenu

            res = rec.get_igr_2(ir+prime_anciennete, rubriques,cotisations_employee_ir)

            if not res['ir_net']==0:
                ir_line = {
                            'name' : 'Impot sur le revenu', 'id_bulletin' : id_bulletin,'type' : 'cotisation','base' : res['salaire_net_imposable'], 'rate_employee' : res['taux'],
                            'subtotal_employee':res['ir_net'],'credit_account_id': res['credit_account_id'], 'debit_account_id' : res['credit_account_id'],'deductible' : True,
                        }
                self.env['hr.payroll_ma.bulletin.line'].create(ir_line)

            for rubrique in rubriques :
                if(rubrique['categorie'] == 'deduction'):
                        deduction += rubrique['montant']
                        deduction_line = {
                        'name' : rubrique['name'], 'id_bulletin' : id_bulletin, 'type' : 'retenu','base' : rubrique['montant'],
                        'rate_employee' : 100, 'subtotal_employee':rubrique['montant'], 'deductible' : True,'afficher' : rubrique['afficher'],
                        'credit_account_id':rubrique['credit_account_id'] or False, 'debit_account_id':rubrique['debit_account_id'] or False
                       }
                        self.env['hr.payroll_ma.bulletin.line'].create(deduction_line)
            salaire_net = salaire_brute - res['ir_net'] - cotisations_employee

            salaire_net_a_payer = salaire_brute - deduction - res['ir_net'] - cotisations_employee
            
            ''' CSS '''
            '''cnss = self.env['hr.payroll_ma.bulletin.line'].search([('id_bulletin', '=', id_bulletin), ('name', '=', 'CNSS')], limit=1).subtotal_employee
            _logger.warning('cnss %s' % (cnss))
            amo = self.env['hr.payroll_ma.bulletin.line'].search([('id_bulletin', '=', id_bulletin), ('name', '=', 'AMO')], limit=1).subtotal_employee
            _logger.warning('amo %s' % (amo))'''
            if bulletin.employee_contract_id.taxe_solidarite == 'fixe':
                exlude_amount = 0
                arr = self.env['hr.payroll_ma.bulletin.line'].search([('id_bulletin', '=', id_bulletin), ('name', '=', 'ASSURANCE RECORE RAM')], limit=1)
                exlude_amount += arr.subtotal_employee if arr else 0
                mrm = self.env['hr.payroll_ma.bulletin.line'].search([('id_bulletin', '=', id_bulletin), ('name', '=', 'MUTUELLE RAM MUPRAS')], limit=1)
                exlude_amount += mrm.subtotal_employee if mrm else 0
                per = self.env['hr.payroll_ma.bulletin.line'].search([('id_bulletin', '=', id_bulletin), ('name', '=', 'PER')], limit=1)
                exlude_amount += per.subtotal_employee if per else 0
                salaire_net_imposable_css = salaire_brute_imposable - res['frais_pro_reelle'] - cotisations_employee + exlude_amount
                #_logger.warning('salaire_net_imposable_css %s' % (salaire_net_imposable_css))
                mt_interets = self.env['hr.payroll.loan.line'].search([('employee_id','=',bulletin.employee_id.id), ('period_id', '=', bulletin.period_id.id)], limit=1).interet_amount if self.env['hr.payroll.loan.line'].search([('employee_id','=',bulletin.employee_id.id), ('period_id', '=', bulletin.period_id.id)], limit=1) else 0
                type_logement = bulletin.employee_id.type_logement
                mt_rabattement = 0
                if mt_interets > 0:
                    if type_logement == 'social' and bulletin.employee_contract_id.wage <= dictionnaire.salaire_max_logement_social:
                        mt_rabattement = mt_interets
                    else:
                        mt_rabattement = min((ir+prime_anciennete-res['frais_pro_reelle']-cotisations_employee_ir)*0.1,mt_interets)
                ir_css = rec.get_igr_2(ir+prime_anciennete , rubriques, cotisations_employee_ir, True)
                _logger.warning('ir_css %s %s %s %s %s' % (res['mt_rabattement'], ir_css['ir_net'], cotisations_employee_ir, cotisations_employee_ir, ir+prime_anciennete))
                # To improve: substruct rubrique not applied for CSS
                rappel = self.env['hr.payroll_ma.bulletin.line'].search([('id_bulletin', '=', id_bulletin), ('name', '=', 'RAPPEL/SAL AMO')], limit=1)
                salaire_net_css = salaire_brute - (rappel.subtotal_employee if rappel else 0) - cotisations_employee - ir_css['ir_net']
                taxe_solidarite = self.env['hr.payroll_ma.rubrique'].search([('name', '=', 'TAXE DE SOLIDARITE')], limit=1)
                #_logger.warning('salaire_net_css %s' % (salaire_net_css))
                if salaire_net_css > 20000:
                    css = salaire_net_css * 0.015
                    salaire_net_a_payer = salaire_net_a_payer - css
                    
                    if css != 0:
                        css_line = {
                                'name' : 'Taxe de solidarité', 'id_bulletin' : id_bulletin, 'type' : 'retenu','base' : salaire_net_css,
                                'rate_employee' : 100, 'subtotal_employee':css, 'deductible' : True, 'afficher' : True,
                                'credit_account_id':taxe_solidarite.credit_account_id.id if taxe_solidarite else False, 
                                'debit_account_id':taxe_solidarite.debit_account_id.id if taxe_solidarite else False
                               }
                        self.env['hr.payroll_ma.bulletin.line'].create(css_line)
                ''' '''
            
            if dictionnaire['arrondi']:
                arrondi=1-(round(salaire_net_a_payer,2)-int(salaire_net_a_payer))
                if  arrondi !=1:
                    diff = salaire_net_a_payer-int(salaire_net_a_payer)
                    arrondi=1-(salaire_net_a_payer-int(salaire_net_a_payer))

                    if diff < 0.5:
                        arrondi = diff*-1
                    else:
                        arrondi = 1-diff

                    arrondi=1-(salaire_net_a_payer-int(salaire_net_a_payer))

                    salaire_net_a_payer+= arrondi
                    arrondi_line= {
                                'name' : 'Arrondi', 'id_bulletin' : id_bulletin, 'type' : 'retenu','base' : arrondi,
                                'rate_employee' : 100, 'subtotal_employee':arrondi, 'deductible' : True,
                               }
                    self.env['hr.payroll_ma.bulletin.line'].create(arrondi_line)
                else :arrondi =0

            rec.salaire_brute = salaire_brute
            rec.salaire_brute_imposable = salaire_brute_imposable
            ''' MO'''''
            rec.salaire_brute_imposable_ir = ir + prime_anciennete
            ''''''''''''
            rec.salaire_net = salaire_net
            rec.salaire_net_a_payer = salaire_net_a_payer
            rec.salaire_net_imposable = res['salaire_net_imposable']
            rec.cotisations_employee = cotisations_employee
            rec.cotisations_employer = cotisations_employer
            rec.igr = res['ir_net']
            rec.prime = prime
            rec.indemnite = indemnite
            rec.avantage = avantage
            rec.deduction = deduction
            rec.prime_anciennete = prime_anciennete
            rec.exoneration = exoneration
            rec.absence = absence
            rec.frais_pro = res['frais_pro']
            rec.personnes = res['personnes']
            rec.arrondi = arrondi
            rec.logement = bulletin.employee_id.logement
            '''rec.calculer_comptage_bulletin()'''



# Classe : Rubrique
class hr_rubrique(models.Model):
    _name = "hr.payroll_ma.rubrique"
    _description = "rubrique"

    name = fields.Char(string='Nom de la rubrique', required="True")
    imposition_ids = fields.One2many('hr.payroll_ma.imposition.rubrique', 'rubrique_id', string="Impositions")
    code = fields.Char(string='Code', required=False, readonly=False)
    categorie = fields.Selection([('majoration', 'Majoration'),('deduction', 'Deduction')], string=u'Catégorie', default='majoration')
    sequence = fields.Integer('Sequence',help=u"Ordre d'affichage dans le bulletin de paie",default=1)
    type = fields.Selection([('prime', 'Prime'),('indemnite', 'Indemnite'),('avantage', 'Avantage')], string='Type', default='prime')
    plafond = fields.Float(string=u'Plafond exonéré CNSS')
    plafond_ir = fields.Float(string=u'Plafond exonéré IR')
    formule_plafond_cnss = fields.Char(string='Formule plafond exonéré CNSS', size=128, required=False,help='''
                    Pour les rubriques de type majoration on utilise les variables suivantes :
                    salaire_base : Salaire de base
                    hour_base : Salaire de l heure
                    normal_hours : Les heures normales
                    working_days : Jours travalles (imposable)
        ''')
    formule_plafond_ir = fields.Char(string='Formule plafond exonéré IR', size=128, required=False,help='''
                    Pour les rubriques de type majoration on utilise les variables suivantes :
                    salaire_base : Salaire de base
                    hour_base : Salaire de l heure
                    normal_hours : Les heures normales
                    working_days : Jours travalles (imposable)
        ''')
    formule = fields.Char(string='Formule', size=128, required=False,help='''
                    Pour les rubriques de type majoration on utilise les variables suivantes :
                    salaire_base : Salaire de base
                    hour_base : Salaire de l heure
                    normal_hours : Les heures normales
                    working_days : Jours travalles (imposable)
        ''')
    imposable = fields.Boolean(string='Imposable',default=False)
    afficher = fields.Boolean(string='Afficher',help='afficher cette rubrique sur le bulletin de paie',default=True)
    ir = fields.Boolean(string='IR', required=False)
    anciennete = fields.Boolean(string=u'Ancienneté')
    absence = fields.Boolean(string='Absence')
    conge = fields.Boolean(string=u'Congé')
    note = fields.Text(string='Commentaire')
    reprise = fields.Boolean(string=u'Reprise')
    
    credit_account_id = fields.Many2one('account.account', string=u'Compte de crédit')
    debit_account_id = fields.Many2one('account.account', string=u'Compte de débit')

    amount_number = fields.Selection([('amount', 'Montant'),('number', 'Nombre')], string='Règle d\'affectation', default='amount')
    coefficient = fields.Float(string='Coefficient', default=1)
    day_hour = fields.Selection([('hour', 'Horaire'),('daily', 'Journalier')], string='Base', default='hour')
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Société',
        required=True,
        default=lambda self: self.env['res.company']._company_default_get()
    )
    '''@api.multi
    def unlink(self):
        for rec in self:
            if rec.non_modifiable:
                raise ValidationError(u"Suppression impossible de la rubrique !!!")
        return super(hr_rubrique, self).unlink()

'''
    # Redéfinition de la méthode write
    '''@api.multi
    def write(self, vals):

        for rec in self:

            if rec.non_modifiable:
                return True
            else:
                rubrique = super(hr_rubrique,self).write(vals)
<group>
						<!--<field name="plafonne" />-->
						<!--<field name="plafond_mt" attrs="{'invisible':[('plafonne','=', True)]}"/>-->
						<!--<field name="plafond_formule" attrs="{'invisible':[('plafonne','=', True)]}"/>-->
						<field name="imposition"/>
					</group>
                return rubrique

'''

# Classe : Ligne rubrique
class hr_ligne_rubrique(models.Model):

    def _sel_rubrique(self, cr, uid, context=None):

        for rec in self:
            obj = self.env['hr.payroll_ma.rubrique']
            res = obj.search([])
            res = [(r.id, r.name) for r in res]
            return res

    _name = "hr.payroll_ma.ligne_rubrique"
    _description = "Ligne Rubrique"
    _order = 'date_start'

    rubrique_id = fields.Many2one('hr.payroll_ma.rubrique', string='Rubrique', selection=_sel_rubrique)
    id_contract = fields.Many2one('hr.contract', string='Ref Contrat', ondelete='cascade', select=True)
    montant = fields.Float(string='Montant')
    taux = fields.Float(string='Taux')
    period_id = fields.Many2one('date.range', domain="[('type_id.fiscal_period','=',True)]" ,string=u'Période')
    permanent = fields.Boolean(string='Rubrique Permanante')
    date_start = fields.Date(string=u'Date début')
    date_stop = fields.Date(string='Date fin')
    note = fields.Text(string='Commentaire')


    @api.constrains('date_stop')
    def _check_date(self):

        for obj in self:
            if obj.date_start > obj.date_stop :
                raise ValidationError(u'Date début doit être inferieur à la date de fin')
            return True


    @api.onchange('rubrique_id')
    def onchange_rubrique_id(self):
        for rec in self:
            rec.montant = rec.rubrique_id.plafond


    @api.onchange('period_id')
    def onchange_period_id(self):
        self.date_start = self.period_id.date_start
        self.date_stop = self.period_id.date_end




class hr_payroll_ma_bulletin_line(models.Model):
    _name = "hr.payroll_ma.bulletin.line"
    _description = "ligne de salaire"

    name = fields.Char(string='Description', size=256, required=True)
    id_bulletin = fields.Many2one('hr.payroll_ma.bulletin', string='Ref Salaire', ondelete='cascade', select=True)
    type = fields.Selection([('other', 'Autre'), ('retenu', 'Retenu'), ('cotisation', 'Cotisation'), ('brute', 'Salaire brute')], string='Type')
    credit_account_id = fields.Many2one('account.account', string=u'Compte crédit', domain=[('type', '<>', 'view'), ('type', '<>', 'closed')], help="The income or expense account related to the selected product.")
    debit_account_id = fields.Many2one('account.account', string=u'Compte Débit', domain=[('type', '<>', 'view'), ('type', '<>', 'closed')], help="The income or expense account related to the selected product.")
    base = fields.Float(string='Base', required=True, digits=(16, 2))
    subtotal_employee = fields.Float(string=u'Montant Employé', digits=(16, 2))
    subtotal_employer = fields.Float(string='Montant Employeur', digits=(16, 2))
    rate_employee = fields.Float(string=u'Taux Employé', digits=(16, 2))
    rate_employer = fields.Float(string='Taux Employeur', digits=(16, 2))
    note = fields.Text(string='Notes')
    deductible = fields.Boolean(string=u'Déductible',default=False)
    afficher = fields.Boolean(string='Afficher',default=True)

class hr_payroll_ma_position_rubrique(models.Model):
    _name = "hr.payroll_ma.imposition.rubrique"
    plafonne = fields.Boolean(string="Plafonné")
    plafond_mt = fields.Float(string="Plafond MT")
    plafond_formule = fields.Char(string="Plafond Formule")
    imposition_id = fields.Many2one('hr.payroll_ma.cotisation',string="Cotisation")
    rubrique_id = fields.Many2one('hr.payroll_ma.rubrique',string="Rubrique")
