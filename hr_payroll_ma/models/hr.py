# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
import time
from odoo.exceptions import except_orm, Warning, RedirectWarning
from datetime import date
from dateutil.relativedelta import relativedelta

# Héritage classe Employé
class hr_employee(models.Model):
    _inherit = 'hr.employee'

    matricule = fields.Char('Matricule')
    cin = fields.Char('CIN', size=64)
    prenom = fields.Char(u'Prénom', size=64)
    date = fields.Date(string=u"Date entrée",default = lambda * a: time.strftime('%Y-%m-%d'), help=u"Cette date est requipe pour le calcul de la prime d'anciennet�")
    anciennete = fields.Boolean(string=u"Prime d'ancienneté",default=True, help=u"Est ce que cet employé benificie de la prime d'ancienneté")
    mode_reglement = fields.Selection([('virement', 'Virement'), ('cheque', u'Chèque'), ('espece', u'Espèce')], string=u'Mode De Réglement',default='virement')
    #bank = fields.Char(string=u'Banque')
    agence = fields.Char(string=u'Agence')
    bank = fields.Many2one('res.bank',string='Banque Marocaine')
    compte = fields.Char(string=u'Compte bancaire')
    chargefam = fields.Integer(string=u'Nombre de personnes à charge',default=0)
    logement = fields.Float('Abattement Fr Logement',default=0)
    type_logement = fields.Selection([('normal','Normal'),('social','Social')],default='normal',string='Type logement')
    superficie_logement = fields.Float(string='Superficie(m²)')
    prix_acquisition_logement = fields.Float(string=u"Prix d'acquisition")
    affilie = fields.Boolean(string=u'Affilié',default=True, help='Est ce qu on va calculer les cotisations pour cet employe')
    address_home = fields.Char(string=u'Adresse personnelle')
    address = fields.Char(string=u'Adresse professionnelle')
    phone_home = fields.Char(string=u'Téléphone Personnel')
    ssnid = fields.Char(string='N CNSS')
    payslip_count = fields.Integer(compute='get_payslip_count')
    cimr_number = fields.Char(
        string='CIMR N°',
    )

    analytic_account_id = fields.Many2one(
        comodel_name='account.analytic.account',
        string='Business Unit',
    )

    analytic_tag_id = fields.Many2one(
        comodel_name='account.analytic.tag',
        string='Business Line',
    )
    
    @api.onchange('birthday')
    def check_birthday_constraint(self):
        birthday = self.birthday
        today = date.today()
        print (relativedelta(birthday, today).years)
        if relativedelta(birthday, today).years < 18:
            raise UserError('Diffrence between Publication date and Response limit date should be 21 days')

    # Contrainte sur logement social
    @api.constrains('superficie_logement','prix_acquisition_logement','type_logement')
    def _check_param_logement_social(self):
        if self.type_logement == 'social':
            # On retrouve les paramètres mis en place
            params = self.env['hr.payroll_ma.parametres']
            dictionnaire = params.search([('company_id','=',self.company_id.id)])

            # On vérifie la superficie
            if self.superficie_logement > dictionnaire['superficie_max_logement_social']:
                raise except_orm(('Attention'), (u"La superficie indiquée n'est pas conforme aux normes du logement social !!!"))

            # On vérifie le prix d'acquisition
            if self.prix_acquisition_logement > dictionnaire['prix_achat_max_logement_social']:
                raise except_orm(('Attention'), (u"Le prix d'acquisition n'est pas conforme aux normes du logement social !!!"))


    def name_get(self):
        result = []
        for rec in self:
            if rec.prenom:
                result.append((rec.id, rec.name + ' ' + rec.prenom))
            else:
                result.append((rec.id, rec.name))
        return result

    def get_payslip_count(self):

        for rec in self:
            count = 0

            count = len(self.env['hr.payroll_ma.bulletin'].search([('employee_id','=',rec.id)]))

            rec.payslip_count = count


# Héritage classe contrat
class hr_contract(models.Model):
    _inherit = "hr.contract"


    working_days_per_month = fields.Integer(string=u'Jours travaillés par mois',default=26)
    hour_salary = fields.Float(u'Salaire Horaire')
    monthly_hour_number = fields.Float(u'Nombre Heures par mois')
    ir = fields.Boolean(u'IR')
    cotisation = fields.Many2one('hr.payroll_ma.cotisation.type', string=u'Type cotisation', required=True)
    rubrique_ids = fields.One2many('hr.payroll_ma.ligne_rubrique', 'id_contract', string='Les rubriques')
    actif = fields.Boolean(string="Actif" ,default=True)
    per_patronal = fields.Float(string='PER Patronal')
    per_salarial = fields.Float(string='PER Salarial')
    taxe_solidarite = fields.Selection([('fixe', 'Revenu fixe'),('variable', 'Revenu variable')], string=u'Taxe de solidarité', default='fixe')

    @api.constrains('actif')
    def _check_unicite_contrat(self):
        contrat_ids = self.env['hr.contract'].search([('employee_id','=',self.employee_id.id),('actif','=',True)])
        print ("contrats"), len(contrat_ids)
        if len(contrat_ids) > 1:
            raise except_orm(('Attention'), (u'Plusieurs contrats actifs pour cet employé!!!'))

    def cloturer_contrat(self):
        for rec in self:
            rec.actif =False
            rec.date_end = fields.Date.context_today(self)


    def activer_contrat(self):

        for rec in self:
            rec.actif =True
            rec.date_end = None

    def net_to_brute(self):

        for rec in self.env['hr.contract'].search([]):
            print (len(self.env['hr.contract'].search([])), rec.id)
            contract = self.env['hr.contract'].browse(rec.id)
            salaire_base = rec.wage
            cotisation = rec.cotisation

            personnes = rec.employee_id.chargefam
            params = self.env['hr.payroll_ma.parametres']
            objet_ir = self.env['hr.payroll_ma.ir']

            liste = objet_ir.search([])
            ids_params = params.search([('company_id','=',rec.company_id.id)])
            dictionnaire = ids_params[0]

            abattement = personnes * dictionnaire.charge

            base = 0
            salaire_brute = salaire_base
            trouve=False
            trouve2=False
            while(trouve == False):
                salaire_net_imposable=0
                cotisations_employee=0
                for cot in cotisation.cotisation_ids :
                    if cot.plafonee and salaire_brute >= cot.plafond:
                        base = cot.plafond
                    else : base = salaire_brute

                    cotisations_employee += base * cot.tauxsalarial / 100
                fraispro = salaire_brute * dictionnaire.fraispro / 100
                if fraispro < dictionnaire.plafond:
                    salaire_net_imposable = salaire_brute - fraispro - cotisations_employee
                else :
                    salaire_net_imposable = salaire_brute - dictionnaire.plafond - cotisations_employee
                for tranche in liste:
                    if(salaire_net_imposable >= tranche.debuttranche/12) and (salaire_net_imposable < tranche.fintranche/12):
                        taux = (tranche.taux)
                        somme = (tranche.somme/12)

                ir = (salaire_net_imposable * taux / 100) - somme - abattement
                if(ir < 0):ir = 0
                salaire_net=salaire_brute - cotisations_employee - ir
                if(int(salaire_net)==int(salaire_base) and trouve2==False):
                    trouve2=True
                    salaire_brute-=1
                if(round(salaire_net,2)==salaire_base):trouve=True
                elif trouve2==False : salaire_brute+=0.5
                elif trouve2==True : salaire_brute+=0.01


            rec.wage = round(salaire_brute,2)
            return True
