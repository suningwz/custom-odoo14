# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import ValidationError

# Classe : Paramètres de la paie
class hr_payroll_ma_parametres(models.Model):
    _name = 'hr.payroll_ma.parametres'
    _description = 'Parametres'
    
    name = fields.Char(string="Name", default='Paramétres globaux')
    smig = fields.Float("SMIG")
    arrondi = fields.Boolean("Arrondi",default=True)
    charge = fields.Float(string="Charges de familles", help="Les charges de famille deduites de IGR")
    fraispro = fields.Float(string="Frais Proffessionnels")
    plafond = fields.Float(string="Plafond")
    #credit_account_id = fields.Many2one('account.account', string='Compte de credit IGR')
    credit_account_id = fields.Many2one('account.account', string='Compte de credit IGR')
    #credit_account_id = fields.Many2one('account.account', string='Compte de credit IGR',default='_get_ir_account')
    partner_id = fields.Many2one('res.partner', string='Partenaire', change_default=True, readonly=True)
    salary_credit_account_id = fields.Many2one('account.account', string='Compte de credit')
    #salary_credit_account_id = fields.Many2one('account.account', string='Compte de credit',default='_get_credit_account')
    salary_debit_account_id = fields.Many2one('account.account', string=u'Compte de debit')
    #salary_debit_account_id = fields.Many2one('account.account', string=u'Compte de debit',default='_get_debit_account')
    #analytic_account_id = fields.Many2one('account.analytic.account', string='Compte analytique')
    salaire_max_logement_social = fields.Float("Salaire max",default=3000)
    superficie_max_logement_social = fields.Float("Superficie max (m²)",default=80)
    prix_achat_max_logement_social = fields.Float("Prix d'achat max",default=300000)
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Société',
        required=True,
        default=lambda self: self.env['res.company']._company_default_get()
    )
    taux_solidatite = fields.Float(string="Taux de la taxe de solidarité")

    def _get_credit_account(self):

        for rec in self:

            account_obj = self.env['account.account']
            res = account_obj.search( [('code', 'like', '4432%')], limit=1)

            if res:
                return res[0]
            else:
                return False

    def _get_debit_account(self):

        for rec in self:

            account_obj = self.env['account.account']
            res = account_obj.search([('code', 'like', '6171%')], limit=1)
            print ('------------ Res '), res
            if res:
                return res[0]
            else:
                return False

    def _get_ir_account(self, cr, uid, context):

        for rec in self:

            account_obj = self.env['account.account']
            res = account_obj.search([('code', 'like', '445250')], limit=1)

            if res:
                return res[0]
            else:
                return False


# Classe : IR
class hr_ir(models.Model):
    _name = 'hr.payroll_ma.ir'
    _description = 'IR'

    debuttranche = fields.Float(string=u"Début de Tranche")
    fintranche = fields.Float(string="Fin de tranche")
    taux = fields.Float(string="taux")
    somme = fields.Float(string=u"Somme a déduire")


# Classe : Ancienneté
class hr_anciennete(models.Model):
    _name = 'hr.payroll_ma.anciennete'
    _description = "Tranches de la prime d'anciennete"

    debuttranche = fields.Float(string=u"Début Tranche")
    fintranche = fields.Float(string=u"Fin Tranche")
    taux = fields.Float(string=u"taux")


# Classe : Cotisation
class hr_cotisation(models.Model):
    _name = 'hr.payroll_ma.cotisation'
    _description = 'Configurer les cotisations'

    code = fields.Char(string="Code")
    name = fields.Char(string="Designation")
    tauxsalarial = fields.Float(string="Taux Salarial")
    tauxpatronal = fields.Float(string="Taux Patronal")
    plafonee = fields.Boolean(string=u'Cotisation plafonée')
    plafond = fields.Float(string=u"Plafond")
    credit_account_id = fields.Many2one('account.account', string=u'Compte de crédit')
    debit_account_id = fields.Many2one('account.account', string=u'Compte de débit')
    non_modifiable = fields.Boolean(string=u'Non Modifiable',default=False)
    absence_pp = fields.Boolean(string='Absence PP')
    absence_ps = fields.Boolean(string='Absence PS')
    base_contract = fields.Boolean(string="A base du contrat")
    technical_name_patronal = fields.Char(string="Nom technique PP")
    technical_name_salarial = fields.Char(string="Nom technique PS")
    type = fields.Selection([('calculated', 'Calculée'),('fixed', 'Fixe')], string='Type', default='calculated')
    amount_salarial = fields.Float(string="Montant Salarial")
    amount_patronal = fields.Float(string="Montant Patronal")
    ir = fields.Boolean('Est déductible de l\'IR', default=True)
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Société',
        required=True,
        default=lambda self: self.env['res.company']._company_default_get()
    )
    
    # Redéfinition de la méthode unlink
    def unlink(self):
        for rec in self:
            if rec.non_modifiable:
                raise ValidationError(u"Suppression impossible")
        return super(hr_cotisation, self).unlink()


    # Redéfinition de la méthode write
    def write(self, vals):

        for rec in self:

            if vals.get('name',"rien") != 'rien' and rec.non_modifiable:
                del vals['name']

            if vals.get('code',"rien") != 'rien'  and rec.non_modifiable:
                del vals['code']

            cotisation = super(hr_cotisation,self).write(vals)

            return cotisation


# Classe : Types de cotisations
class hr_cotisation_type(models.Model):
    _name = 'hr.payroll_ma.cotisation.type'
    _description = 'Configurer les types de cotisation'

    name = fields.Char(string=u"Désignation")
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Société',
        required=True,
        default=lambda self: self.env['res.company']._company_default_get()
    )
    cotisation_ids = fields.Many2many('hr.payroll_ma.cotisation', 'salary_cotisation', 'cotisation_id', 'cotisation_type_id', string='Cotisations')

    # ------------------------------------------------------------------------
    # METHODS
    # ------------------------------------------------------------------------

    def name_get(self):
        result = []
        for record in self:
            name = record.name + '(' + record.company_id.name + ')'
            result.append((record.id, name))
        return result
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:

