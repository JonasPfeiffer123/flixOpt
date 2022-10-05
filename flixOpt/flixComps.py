# -*- coding: utf-8 -*-
"""
Created on Thu Sep 10 13:45:12 2020

@author: Panitz

# references: 
#   from flixopt 1.0  : structure / features / math, constraints, ...
#   from oemof        : some name-definition/ some structure
"""

# TODO:
#  optionale Flows einführen -> z.b. Asche: --> Bei denen kommt keine Fehlermeldung, wenn nicht verknüpft und nicht aktiviert/genutzt
#  cVariable(,...,self,modBox,...) -> modBox entfernen und lieber über self.modBox aufrufen -> kürzer!
#  Hilfsenergiebedarf als Feature einführen?
#  self.xy = cVariable('xy'), -> kürzer möglich, in cVariabe() über aComponent.addAttribute()
#  Variablen vielleicht doch bei allen Komponenten lieber unter var_struct abspeichern ?

import numpy as np

import flixOptHelperFcts as helpers
from basicModeling import *  # Modelliersprache
from flixStructure import *  # Grundstruktur
from flixFeatures import *


class cBaseLinearTransformer(cBaseComponent):
    """
    Klasse cBaseLinearTransformer: Grundgerüst lineare Übertragungskomponente
    """
    new_init_args = [cArg('inputs', 'flowList', 'flowList', 'Liste aller Input-Flows'),
                     cArg('outputs', 'flowList', 'flowList', 'Liste aller Output-Flows'),
                     cArg('factor_Sets', 'factor_Sets', 'factor_Sets',
                          'Beschreibungs-Flow-ZH: Gleichungen via factor_Sets, rezessiv!'),
                     cArg('segmentsOfFlows', 'segmentsOfFlows', 'segmentsOfFlows',
                          'Beschreibung-Flow-ZH: Abschnittsweise Lineare Beschreibung, dominant!')]
    not_used_args = []

    def __init__(self, label, inputs, outputs, factor_Sets, segmentsOfFlows=None, **kwargs):
        # factor_Sets:
        # Gleichungen: sum (factor * flow_in) = sum (factor * flow_out)
        # Faktoren können bereits cTS_vector sein!
        # factor_Sets= [{Q_th: COP_th , Q_0 : 1},                          #
        #               {P_el: COP_el , Q_0 : 1},                          # COP_th
        #               {Q_th: 1 , P_el: 1, Q_0 : 1, Q_ab: 1}] # Energiebilanz

        # segments: Abschnittsweise linear. Anfang und Ende von Abschnitt angeben.
        #           Faktoren können auch Listen sein!!!
        #           Wenn Anfang von Abschnitt n+1 nicht Ende von Abschnitt n, dann "Lücke" d.h. nicht zulässiger Bereich
        # segments = {Q_fu: [ 5  , 10,  10, 22], # Abschnitte von 5 bis 10 und 10 bis 22
        #             P_el: [ 2  , 5,    5, 8 ],
        #             Q_fu: [ 2.5, 4,    4, 12]}
        #             --> auch Punkte können über Segment ausgedrückt werden, d.h. z.B [5, 5]
        #

        super().__init__(label, **kwargs)
        # args to attributes:
        self.inputs = inputs
        self.outputs = outputs
        self.factor_Sets = factor_Sets
        self.segmentsOfFlows = segmentsOfFlows

    def transformFactorsToTS(self, factor_Sets):
        """
        macht alle Faktoren, die nicht cTS_vector sind, zu cTS_vector

        :param factor_Sets:
        :return:
        """
        # Einzelne Faktoren zu Vektoren:
        factor_Sets_TS = []
        # für jedes Dict -> Values (=Faktoren) zu Vektoren umwandeln:
        for aFactor_Dict in factor_Sets:  # Liste of dicts
            # Transform to TS:
            aFactor_Dict_TS = transformDictValuesToTS('Faktor', aFactor_Dict, self)
            factor_Sets_TS.append(aFactor_Dict_TS)
            # check flows:
            for flow in aFactor_Dict_TS:
                if not (flow in self.inputs + self.outputs):
                    raise Exception(self.label + ': Flow ' + flow.label + ' in Factor_Set ist nicht in inputs/outputs')
        return factor_Sets_TS

    def finalize(self):
        """

        :return:
        """
        super().finalize()

        # factor-sets:
        if self.segmentsOfFlows is None:

            # TODO: mathematisch für jeden Zeitschritt checken!!!!
            #  Anzahl Freiheitsgrade checken: =  Anz. Variablen - Anz. Gleichungen

            # alle Faktoren, die noch nicht TS_vector sind, umwandeln:
            self.factor_Sets = self.transformFactorsToTS(self.factor_Sets)

            self.degreesOfFreedom = (len(self.inputs) + len(self.outputs)) - len(self.factor_Sets)
            if self.degreesOfFreedom <= 0:
                raise Exception(self.label + ': ' + str(len(self.factor_Sets)) + ' Gleichungen VERSUS '
                                + str(len(self.inputs+self.outputs)) + ' Variablen!!!')

        # linear segments:
        else:
            # Flow als Keys rauspicken und alle Stützstellen als cTS_Vector:
            self.segmentsOfFlows_TS = self.segmentsOfFlows
            for aFlow in self.segmentsOfFlows.keys():
                # 2. Stützstellen zu cTS_vector machen, wenn noch nicht cTS_vector!:
                for i in range(len(self.segmentsOfFlows[aFlow])):
                    stuetzstelle = self.segmentsOfFlows[aFlow][i]
                    self.segmentsOfFlows_TS[aFlow][i] = cTS_vector('Stuetzstelle', stuetzstelle, self)

            def get_var_on():
                return self.mod.var_on

            self.feature_linSegments = cFeatureLinearSegmentSet('linearSegments', self, self.segmentsOfFlows_TS,
                                                                get_var_on=get_var_on,
                                                                checkListOfFlows=self.inputs + self.outputs)  # erst hier, damit auch nach __init__() noch Übergabe möglich.

    def declareVarsAndEqs(self,modBox:cModelBoxOfES):
        """
        Deklarieren von Variablen und Gleichungen

        :param modBox:
        :return:
        """
        super().declareVarsAndEqs(modBox)  # (ab hier sollte auch self.mod.var_on dann vorhanden sein)

        # factor-sets:
        if self.segmentsOfFlows is None:
            pass
        # linear segments:
        else:
            self.feature_linSegments.declareVarsAndEqs(modBox)

    def doModeling(self,modBox:cModelBoxOfES,timeIndexe):
        """
        Durchführen der Modellierung?

        :param modBox:
        :param timeIndexe:
        :return:
        """
        super().doModeling(modBox, timeIndexe)
        # factor_Sets:
        if self.segmentsOfFlows is None:
            # Transformer-Constraints:

            inputs_set = set(self.inputs)
            outputs_set = set(self.outputs)

            # für alle linearen Gleichungen:
            for i in range(len(self.factor_Sets)):
                # erstelle Gleichung für jedes t:
                # sum(inputs * factor) = sum(outputs * factor)
                # in1.val[t] * factor_in1[t] + in2.val[t] * factor_in2[t] + ... = out1.val[t] * factor_out1[t] + out2.val[t] * factor_out2[t] + ...

                aFactorVec_Dict = self.factor_Sets[i]

                leftSideFlows = inputs_set & aFactorVec_Dict.keys()  # davon nur die input-flows, die in Glg sind.
                rightSideFlows = outputs_set & aFactorVec_Dict.keys()  # davon nur die output-flows, die in Glg. sind.

                eq_linearFlowRelation_i = cEquation('linearFlowRelation_' + str(i), self, modBox)
                for inFlow in leftSideFlows:
                    aFactor = aFactorVec_Dict[inFlow].d_i
                    eq_linearFlowRelation_i.addSummand(inFlow.mod.var_val, aFactor)  # input1.val[t]      * factor[t]
                for outFlow in rightSideFlows:
                    aFactor = aFactorVec_Dict[outFlow].d_i
                    eq_linearFlowRelation_i.addSummand(outFlow.mod.var_val, -aFactor)  # output.val[t] * -1 * factor[t]

                eq_linearFlowRelation_i.addRightSide(0)  # nur zur Komplettisierung der Gleichung

        # (linear) segments:
        # Zusammenhänge zw. inputs & outputs können auch vollständig über Segmente beschrieben werden:
        else:
            self.feature_linSegments.doModeling(modBox, timeIndexe)

    def print(self, shiftChars):
        """
        Ausgabe von irgendwas?

        :param shiftChars:
        :return:
        """
        super().print(shiftChars)
        # attribut hat es nur bei factor_sets:
        if hasattr(self, 'degreesOfFreedom'):
            print(shiftChars + '  ' + 'Degr. of Freedom: ' + str(self.degreesOfFreedom))

    # todo: checkbounds!
    # def initializeParameter(self,aStr,aBounds):
    # private Variable:
    #     self._eta          = aBounds['eta'][0]
    # exec('self.__' + aStr + ' = aBounds[0] ')
    # property dazu:
    #    self.eta            = property(lambda s: s.__get_param('eta'), lambda s,v: s.__set_param(v,'eta')')
    # exec('self.'   + aStr + ' = property(lambda s: s.__get_param(aStr) , lambda s,v: s.__set_param(v,aStr ))')

    def setLinearSegments(self, segmentsOfFlows):
        """

        :param segmentsOfFlows:
        :return:
        """
        self.segmentsOfFlows = segmentsOfFlows  # attribute of mother-class


class cKessel(cBaseLinearTransformer):
    """
    Klasse cKessel
    """
    new_init_args = [cArg('label', 'param', 'str', 'Bezeichnung'),
                     cArg('eta', 'param', 'TS', 'Wirkungsgrad'),
                     cArg('Q_fu', 'flow', 'flow', 'input-Flow Brennstoff'),
                     cArg('Q_th', 'flow', 'flow', 'output-Flow Wärme')]

    not_used_args = ['label', 'inputs', 'outputs', 'factor_Sets']

    def __init__(self, label, eta, Q_fu, Q_th, **kwargs):
        """
        Konstruktor für Instanzen der Klasse cKessel

        :param str label: Bezeichnung
        :param int or float eta: Wirkungsgrad
        :param cFlow Q_fu: input-Flow Brennstoff
        :param cFlow Q_th: output-Flow Wärme
        :param kwargs:
        """
        # super:
        kessel_bilanz = {Q_fu: eta,
                         Q_th: 1}  # eq: eta * Q_fu = 1 * Q_th # TODO: Achtung eta ist hier noch nicht TS-vector!!!

        super().__init__(label, inputs=[Q_fu], outputs=[Q_th], factor_Sets=[kessel_bilanz], **kwargs)

        # args to attributes:
        self.eta = cTS_vector('eta', eta, self)  # thermischer Wirkungsgrad
        self.Q_fu = Q_fu
        self.Q_th = Q_th

        # allowed medium:
        Q_fu.setMediumIfNotSet(cMediumCollection.fu)
        Q_th.setMediumIfNotSet(cMediumCollection.heat)

        # Plausibilität eta:
        self.eta_bounds = [0 + 1e-10, 1 - 1e-10]  # 0 < eta_th < 1
        helpers.checkBoundsOfParameter(eta, 'eta', self.eta_bounds, self)

        # # generische property für jeden Koeffizienten
        # self.eta = property(lambda s: s.__get_coeff('eta'), lambda s,v: s.__set_coeff(v,'eta'))


class cHeatPump(cBaseLinearTransformer):
    """
    Klasse cHeatPump
    """
    new_init_args = [cArg('label', 'param', 'str', 'Bezeichnung'),
                     cArg('COP', 'param', 'TS', 'Coefficient of Performance'),
                     cArg('P_el', 'flow', 'flow', 'input-Flow Strom'),
                     cArg('Q_th', 'flow', 'flow', 'output-Flow Wärme')]

    not_used_args = ['label', 'inputs', 'outputs', 'factor_Sets']

    def __init__(self, label, COP, P_el, Q_th, **kwargs):
        """
        Konstruktor für Instanzen der Klasse cHeatPump

        :param label:
        :param COP:
        :param P_el:
        :param Q_th:
        :param kwargs:
        """
        # super:
        heatPump_bilanz = {P_el: COP, Q_th: 1}  # TODO: Achtung eta ist hier noch nicht TS-vector!!!
        super().__init__(label, inputs=[P_el], outputs=[Q_th], factor_Sets=[heatPump_bilanz], **kwargs)

        # args to attributes:
        self.COP = cTS_vector('COP', COP, self)  # thermischer Wirkungsgrad
        self.P_el = P_el
        self.Q_th = Q_th

        # allowed medium:
        P_el.setMediumIfNotSet(cMediumCollection.el)
        Q_th.setMediumIfNotSet(cMediumCollection.heat)

        # Plausibilität eta:
        self.eta_bounds = [0 + 1e-10, 10 - 1e-10]  # 0 < eta_th < 1
        helpers.checkBoundsOfParameter(COP, 'COP', self.eta_bounds, self)


class cCoolingTower(cBaseLinearTransformer):
    """
    Klasse cCoolingTower
    """
    new_init_args = [cArg('label', 'param', 'str', 'Bezeichnung'),
                     cArg('specificElectricityDemand', 'param', 'TS',
                          'spezifischer Hilfsenergiebedarf, z.B. 0.02 (2 %) der Wärmeleistung'),
                     cArg('P_el', 'flow', 'flow', 'input-Flow: Strom (Hilfsenergiebedarf)'),
                     cArg('Q_th', 'flow', 'flow', 'input-Flow: Abwärme')]

    not_used_args = ['label', 'inputs', 'outputs', 'factor_Sets']

    def __init__(self, label, specificElectricityDemand, P_el, Q_th, **kwargs):
        """
        Konstruktor für Instanzen der Klasse cCoolingTower

        :param label:
        :param specificElectricityDemand:
        :param P_el:
        :param Q_th:
        :param kwargs:
        """
        # super:         
        auxElectricity_eq = {P_el: 1,
                             Q_th: -specificElectricityDemand}  # eq: 1 * P_el - specificElectricityDemand * Q_th = 0  # TODO: Achtung eta ist hier noch nicht TS-vector!!!
        super().__init__(label, inputs=[P_el, Q_th], outputs=[], factor_Sets=[auxElectricity_eq], **kwargs)

        # args to attributes:
        self.specificElectricityDemand = cTS_vector('specificElectricityDemand', specificElectricityDemand,
                                                    self)  # thermischer Wirkungsgrad
        self.P_el = P_el
        self.Q_th = Q_th

        # allowed medium:
        P_el.setMediumIfNotSet(cMediumCollection.el)
        Q_th.setMediumIfNotSet(cMediumCollection.heat)

        # Plausibilität eta:
        self.specificElectricityDemand_bounds = [0, 1]  # 0 < eta_th < 1
        helpers.checkBoundsOfParameter(specificElectricityDemand, 'specificElectricityDemand',
                                       self.specificElectricityDemand_bounds, self)


class cKWK(cBaseLinearTransformer):
    """
    Klasse cKWK
    """
    new_init_args = [cArg('label', 'param', 'str', 'Bezeichnung'),
                     cArg('eta_th', 'param', 'TS', 'el. Wirkungsgrad'),
                     cArg('eta_el', 'param', 'TS', 'th. Wirkungsgrad'),
                     cArg('Q_fu', 'flow', 'flow', 'in-Flow Brennstoff'),
                     cArg('P_el', 'flow', 'flow', 'out-Flow Strom'),
                     cArg('Q_th', 'flow', 'flow', 'out-Flow Wärme')]

    not_used_args = ['label', 'inputs', 'outputs', 'factor_Sets']

    # eta = 1 # Thermischer Wirkungsgrad
    # __eta_bound = [0,1]

    def __init__(self, label, eta_th, eta_el, Q_fu, P_el, Q_th, **kwargs):
        """
        Konstruktor für Instanzen der Klasse cKWK

        :param str label: Bezeichnung
        :param int or float eta_th: thermischer Wirkungsgrad (0 ... 1)
        :param int or float eta_el: elektrischer Wirkungsgrad (0 ... 1)
        :param cFlow Q_fu: in-Flow Brennstoff
        :param cFlow P_el: out-Flow Strom
        :param cFlow Q_th: out-Flow Wärme
        :param kwargs:
        """
        # super:
        waerme_glg = {Q_fu: eta_th, Q_th: 1}
        strom_glg = {Q_fu: eta_el, P_el: 1}
        #                      inputs         outputs               lineare Gleichungen
        super().__init__(label, inputs=[Q_fu], outputs=[P_el, Q_th], factor_Sets=[waerme_glg, strom_glg], **kwargs)

        # args to attributes:
        self.eta_th = cTS_vector('eta_th', eta_th, self)
        self.eta_el = cTS_vector('eta_el', eta_el, self)
        self.Q_fu = Q_fu
        self.P_el = P_el
        self.Q_th = Q_th

        # allowed medium:
        Q_fu.setMediumIfNotSet(cMediumCollection.fu)
        Q_th.setMediumIfNotSet(cMediumCollection.heat)
        P_el.setMediumIfNotSet(cMediumCollection.el)

        # Plausibilität eta:
        self.eta_th_bounds = [0 + 1e-10, 1 - 1e-10]  # 0 < eta_th < 1
        self.eta_el_bounds = [0 + 1e-10, 1 - 1e-10]  # 0 < eta_el < 1

        helpers.checkBoundsOfParameter(eta_th, 'eta_th', self.eta_th_bounds, self)
        helpers.checkBoundsOfParameter(eta_el, 'eta_el', self.eta_el_bounds, self)
        if eta_th + eta_el > 1:
            raise Exception('Fehler in ' + self.label + ': eta_th + eta_el > 1 !')


class cStorage(cBaseComponent):
    """
    Klasse cStorage
    """

    # TODO: Dabei fällt mir auf. Vielleicht sollte man mal überlegen, ob man für Ladeleistungen bereits in dem
    #  jeweiligen Zeitschritt mit einem Verlust berücksichtigt. Zumindest für große Zeitschritte bzw. große Verluste
    #  eventuell relevant.
    #  -> Sprich: speicherverlust = charge_state(t) * fracLossPerHour * dt + 0.5 * Q_lade(t) * dt * fracLossPerHour * dt
    #  -> müsste man aber auch für den sich ändernden Ladezustand berücksichtigten

    # costs_default = property(get_costs())
    # param_defalt  = property(get_params())

    new_init_args = [cArg('label'               , 'param', 'str',   'Bezeichnung'),
                     cArg('capacity_inFlowHours', 'param', 'skalar', 'speicherbare Menge, z.B. kWh, m³'),
                     cArg('max_rel_chargeState' , 'param', 'TS'  , 'relative Max-Füllstand'),
                     cArg('min_rel_chargeState' , 'param', 'TS'  , 'relative Min-Füllstand'),
                     cArg('charge_state_end_min', 'param', 'skalar','minimaler Speicherzustand am Ende (nach letztem Zeitschritt)'),
                     cArg('charge_state_end_max', 'param', 'skalar','maximaler Speicherzustand am Ende (nach letztem Zeitschritt)'),
                     cArg('eta_load'            , 'param', 'TS',    'Belade-Wirkungsgrad'),
                     cArg('eta_unload'          , 'param', 'TS',    'Entlade-Wirkungsgrad'),
                     cArg('fracLossPerHour'     , 'param', 'TS',    'Verlust pro Speicherinhalt und Stunde, z.B. 0.02 (= 2 %) pro Stunde'),
                     cArg('avoidInAndOutAtOnce' , 'param', 'boolean', 'soll gleichzeitiges Be- und Entladen vermieden werden? (Achtung Performance wird ggf. kleiner)'),
                     cArg('costsIfVariableCapacity_perFlowHour', 'costs', 'skalar', 'spezifische Speicherkosten (z.B. €/kWh) --> Eingabe nur wenn Speichergröße freie Optimierungsgröße'),
                     cArg('inFlow'              , 'flow',  'flow',  'in-Flow Beladung'),
                     cArg('outFlow'             , 'flow',  'flow',  'out-Flow Entladung')]

    not_used_args = ['label']

    # capacity_inFlowHours: float, 'lastValueOfSim', None
    def __init__(self, label, inFlow, outFlow, capacity_inFlowHours, min_rel_chargeState=0, max_rel_chargeState=1,
                 chargeState0_inFlowHours=0, charge_state_end_min=0, charge_state_end_max=None, eta_load=1,
                 eta_unload=1, fracLossPerHour=0, avoidInAndOutAtOnce=False, investArgs=None, **kwargs):
        """
        Konstruktor für Instanzen der Klasse cStorage

        :param str label: Bezeichnung
        :param cFlow inFlow: eingehender Flow
        :param cFlow outFlow: ausgehender Flow
        :param int or float capacity_inFlowHours: Speicherkapazität in kWh
        :param int or float min_rel_chargeState:
        :param int or float max_rel_chargeState:
        :param int or float chargeState0_inFlowHours: Speicherkapazität in kWh zu Beginn des Betrachtungszeitraums
        :param float charge_state_end_min: minimaler relativer (?) Speicherstand zum Ende des Betrachtungszeitraums (0...1)
        :param float charge_state_end_max: maximaler relativer (?) Speicherstand zum Ende des Betrachtungszeitraums (0...1)
        :param int or float eta_load: Wirkungsgrad beim Laden (0...1)
        :param int or float eta_unload: Wirkungsgrad beim Entladen (0...1)
        :param int or float fracLossPerHour: Verlust pro Speichereinheit und Stunde TODO: pro Stunde oder pro Zeitschritt?
        :param bool avoidInAndOutAtOnce: soll gleichzeitiges Be- und Entladen vermieden werden? (Achtung, Performance wird ggf. schlechter)
        :param cInvestArgs investArgs:
        :param kwargs:
        """
        # charge_state_end_min (absolute Werte, aber relative wären ggf. auch manchmal hilfreich)
        super().__init__(label, **kwargs)

        # args to attributes:
        self.inputs = [inFlow]
        self.outputs = [outFlow]
        self.inFlow = inFlow
        self.outFlow = outFlow
        self.capacity_inFlowHours = capacity_inFlowHours
        self.max_rel_chargeState = cTS_vector('max_rel_chargeState', max_rel_chargeState, self)
        self.min_rel_chargeState = cTS_vector('min_rel_chargeState', min_rel_chargeState, self)
        self.chargeState0_inFlowHours = chargeState0_inFlowHours
        self.charge_state_end_min = charge_state_end_min

        if charge_state_end_max is None:
            # Verwende Lösungen bis zum vollen Speicher
            self.charge_state_end_max = self.capacity_inFlowHours
        else:
            self.charge_state_end_max = charge_state_end_max
        self.eta_load = cTS_vector('eta_load', eta_load, self)
        self.eta_unload = cTS_vector('eta_unload', eta_unload, self)
        self.fracLossPerHour = cTS_vector('fracLossPerHour', fracLossPerHour, self)
        self.avoidInAndOutAtOnce = avoidInAndOutAtOnce

        self.investArgs = investArgs
        self.featureInvest = None

        if self.avoidInAndOutAtOnce:
            self.featureAvoidInAndOut = cFeatureAvoidFlowsAtOnce('feature_avoidInAndOutAtOnce', self,
                                                                 [self.inFlow, self.outFlow])

        if self.investArgs is not None:
            self.featureInvest = cFeatureInvest('used_capacity_inFlowHours', self, self.investArgs,
                                                min_rel=self.min_rel_chargeState,
                                                max_rel=self.max_rel_chargeState,
                                                val_rel=None,  # kein vorgegebenes Profil
                                                investmentSize=self.capacity_inFlowHours,
                                                featureOn=None)  # hier gibt es kein On-Wert

        # Medium-Check:
        if not (cMediumCollection.checkIfFits(inFlow.medium, outFlow.medium)):
            raise Exception('in cStorage ' + self.label + ': input.medium = ' + str(inFlow.medium) +
                            ' and output.medium = ' + str(outFlow.medium) + ' don`t fit!')
        # TODO: chargeState0 darf nicht größer max usw. abfangen!

        self.isStorage = True  # for postprocessing

    def declareVarsAndEqs(self, modBox:cModelBoxOfES):
        """
        Deklarieren von Variablen und Gleichungen

        :param modBox:
        :return:
        """
        super().declareVarsAndEqs(modBox)

        # Variablen:

        if self.featureInvest is None:
            lb = self.min_rel_chargeState.d_i * self.capacity_inFlowHours
            ub = self.max_rel_chargeState.d_i * self.capacity_inFlowHours
            fix_value = None
        else:
            (lb, ub, fix_value) = self.featureInvest.getMinMaxOfDefiningVar()
        # todo: lb und ub muss noch um ein Element (chargeStateEnd_max, chargeStateEnd_min oder aber jeweils None) ergänzt werden!

        self.mod.var_charge_state = cVariableB('charge_state', modBox.nrOfTimeSteps + 1, self, modBox, min=lb, max=ub,
                                               value=fix_value)  # Eins mehr am Ende!
        self.mod.var_charge_state.activateBeforeValues(self.chargeState0_inFlowHours, True)
        self.mod.var_nettoFlow = cVariable('nettoFlow', modBox.nrOfTimeSteps, self, modBox,
                                           min=-np.inf)  # negative Werte zulässig!

        # erst hier, da definingVar vorher nicht belegt!
        if self.featureInvest is not None:
            self.featureInvest.setDefiningVar(self.mod.var_charge_state, None)  # None, da kein On-Wert
            self.featureInvest.declareVarsAndEqs(modBox)

        # obj.vars.Q_Ladezustand   .setBoundaries(0, obj.inputData.Q_Ladezustand_Max);
        # obj.vars.Q_th_Lade       .setBoundaries(0, inf);
        # obj.vars.Q_th_Entlade    .setBoundaries(0, inf);

        # ############ Variablen ###############

        # obj.addVariable('Q_th'             ,obj.lengthOfTS  , 0);
        # obj.addVariable('Q_th_Lade'        ,obj.lengthOfTS  , 0);
        # obj.addVariable('Q_th_Entlade'     ,obj.lengthOfTS  , 0);
        # obj.addVariable('Q_Ladezustand'    ,obj.lengthOfTS+1, 0);  % Eins mehr am Ende!
        # obj.addVariable('IchLadeMich'      ,obj.lengthOfTS  , 1);  % binäre Variable um zu verhindern, dass gleichzeitig Be- und Entladen wird (bei KWK durchaus ein Kostenoptimum)
        # obj.addVariable('IchEntladeMich'   ,obj.lengthOfTS  , 1);  % binäre Variable um zu verhindern, dass gleichzeitig Be- und Entladen wird (bei KWK durchaus ein Kostenoptimum)

        # ############### verknüpfung mit anderen Variablen ##################
        # % Pumpstromaufwand Beladen/Entladen
        # refToStromLastEq.addSummand(obj.vars.Q_th_Lade   ,-1*obj.inputData.spezifPumpstromAufwandBeladeEntlade); % für diese Komponenten Stromverbrauch!
        # refToStromLastEq.addSummand(obj.vars.Q_th_Entlade,-1*obj.inputData.spezifPumpstromAufwandBeladeEntlade); % für diese Komponenten Stromverbrauch!

    def getInitialStatesOfNextSection(timeIndex):
        """
        TODO: was passiert hier? Zuweisungen noch nicht richtig?

        :return:
        """
        initialStates['chargeState0_inFlowHours'] = charge_state[timeIndexe[0]]
        return initialStates

    def doModeling(self, modBox, timeIndexe):
        """
        Durchführen der Modellierung?

        :param modBox:
        :param timeIndexe:
        :return:
        """
        super().doModeling(modBox, timeIndexe)

        # Gleichzeitiges Be-/Entladen verhindern:
        if self.avoidInAndOutAtOnce: self.featureAvoidInAndOut.doModeling(modBox, timeIndexe)

        # % Speicherladezustand am Start
        if self.chargeState0_inFlowHours is None:
            # Startzustand bleibt Freiheitsgrad
            pass
        elif helpers.is_number(self.chargeState0_inFlowHours):
            # eq: Q_Ladezustand(1) = Q_Ladezustand_Start;
            self.eq_charge_state_start = cEquation('charge_state_start', self, modBox, eqType='eq')
            self.eq_charge_state_start.addRightSide(self.mod.var_charge_state.beforeVal())  # chargeState_0 !
            self.eq_charge_state_start.addSummand(self.mod.var_charge_state, 1, timeIndexe[0])
        elif self.chargeState0_inFlowHours == 'lastValueOfSim':
            # eq: Q_Ladezustand(1) - Q_Ladezustand(end) = 0;
            self.eq_charge_state_start = cEquation('charge_state_start', self, modBox, eqType='eq')
            self.eq_charge_state_start.addSummand(self.mod.var_charge_state, 1, timeIndexe[0])
            self.eq_charge_state_start.addSummand(self.mod.var_charge_state, -1, timeIndexe[-1])
        else:
            raise Exception('chargeState0_inFlowHours has undefined value = ' + str(chargeState0_inFlowHours))

        # Speicherleistung / Speicherladezustand / Speicherverlust
        #                                                                          | Speicher-Beladung       |   |Speicher-Entladung                |
        # Q_Ladezustand(n+1) + (-1+VerlustanteilProStunde*dt(n)) *Q_Ladezustand(n) -  dt(n)*eta_Lade*Q_th_Lade(n) +  dt(n)* 1/eta_Entlade*Q_th_Entlade(n)  = 0

        # charge_state hat ein Index mehr:
        timeIndexeChargeState = range(timeIndexe.start, timeIndexe.stop + 1)
        self.eq_charge_state = cEquation('charge_state', self, modBox, eqType='eq')
        self.eq_charge_state.addSummand(self.mod.var_charge_state,
                                        -1 * (1 - self.fracLossPerHour.d_i * modBox.dtInHours),
                                        timeIndexeChargeState[:-1])  # sprich 0 .. end-1 % nach letztem Zeitschritt gibt es noch einen weiteren Ladezustand!
        self.eq_charge_state.addSummand(self.mod.var_charge_state, 1, timeIndexeChargeState[1:])  # 1:end
        self.eq_charge_state.addSummand(self.inFlow.mod.var_val, -1 * self.eta_load.d_i * modBox.dtInHours)
        self.eq_charge_state.addSummand(self.outFlow.mod.var_val,
                                        1 / self.eta_unload.d_i * modBox.dtInHours)  # Achtung hier 1/eta!

        # Speicherladezustand am Ende
        # -> eigentlich min/max-Wert für variable, aber da nur für ein Element hier als Glg:
        # 1: eq:  Q_charge_state(end) <= Q_max
        self.eq_charge_state_end_max = cEquation('eq_charge_state_end_max', self, modBox, eqType='ineq')
        self.eq_charge_state_end_max.addSummand(self.mod.var_charge_state, 1, timeIndexeChargeState[-1])
        self.eq_charge_state_end_max.addRightSide(self.charge_state_end_max)

        # 2: eq: - Q_charge_state(end) <= - Q_min
        self.eq_charge_state_end_min = cEquation('eq_charge_state_end_min', self, modBox, eqType='ineq')
        self.eq_charge_state_end_min.addSummand(self.mod.var_charge_state, -1, timeIndexeChargeState[-1])
        self.eq_charge_state_end_min.addRightSide(- self.charge_state_end_min)

        # nettoflow:
        # eq: nettoFlow(t) - outFlow(t) + inFlow(t) = 0
        self.eq_nettoFlow = cEquation('nettoFlow', self, modBox, eqType='eq')
        self.eq_nettoFlow.addSummand(self.mod.var_nettoFlow, 1)
        self.eq_nettoFlow.addSummand(self.inFlow.mod.var_val, 1)
        self.eq_nettoFlow.addSummand(self.outFlow.mod.var_val, -1)

        if self.featureInvest is not None:
            self.featureInvest.doModeling(modBox, timeIndexe)

        # ############# Gleichungen ##########################
        # % Speicherleistung an Bilanzgrenze / Speicher-Ladung / Speicher-Entladung
        # % Q_th(n) + Q_th_Lade(n) - Q_th_Entlade(n) = 0;
        # obj.eqs.Leistungen = cEquation('Leistungen');
        # obj.eqs.Leistungen.addSummand(obj.vars.Q_th        , 1);
        # obj.eqs.Leistungen.addSummand(obj.vars.Q_th_Lade   , 1);
        # obj.eqs.Leistungen.addSummand(obj.vars.Q_th_Entlade,-1);

        # % Bedingungen der binären Variable "IchLadeMich"
        # Q_th_Lade_Max   = obj.inputData.Q_Ladezustand_Max / obj.inputData.eta_Lade /obj.dt; % maximale Entladeleistung, wenn in einem Zeitschritt alles ausgeschoben wird
        # Q_th_Lade_Min   = 0; % könnte eigtl auch größer Null sein.
        # obj.addConstraintsOfVariableOn(obj.vars.IchLadeMich   ,obj.vars.Q_th_Lade   ,Q_th_Lade_Max   ,Q_th_Lade_Min); % korrelierende Leistungsvariable und ihr Maximum!

        # % Bedingungen der binären Variable "IchEntladeMich"
        # Q_th_Entlade_Max = obj.inputData.Q_Ladezustand_Max * obj.inputData.eta_Entlade /obj.dt; % maximale Entladeleistung, wenn in einem Zeitschritt alles ausgeschoben wird
        # Q_th_Entlade_min = 0; % könnte eigtl auch größer Null sein.
        # obj.addConstraintsOfVariableOn(obj.vars.IchEntladeMich,obj.vars.Q_th_Entlade,Q_th_Entlade_Max,Q_th_Entlade_min);  % korrelierende Leistungsvariable und ihr Maximum!

        # % Bedingung "Laden ODER Entladen ODER nix von beiden" (insbesondere für KWK-Anlagen wichtig, da gleichzeitiges Entladen und Beladen sonst Kostenoptimum sein kann
        # % eq: IchLadeMich(n) + IchEntladeMich(n) <= 1;
        # obj.ineqs.EntwederLadenOderEntladen = cEquation('EntwederLadenOderEntladen');
        # obj.ineqs.EntwederLadenOderEntladen.addSummand(obj.vars.IchLadeMich   ,1);
        # obj.ineqs.EntwederLadenOderEntladen.addSummand(obj.vars.IchEntladeMich,1);
        # obj.ineqs.EntwederLadenOderEntladen.addRightSide(1);

    def addShareToGlobals(self, globalComp: cGlobal, modBox):
        """

        :param globalComp:
        :param modBox:
        :return:
        """
        super().addShareToGlobals(globalComp, modBox)

        if self.featureInvest is not None:
            self.featureInvest.addShareToGlobals(globalComp, modBox)


class cSourceAndSink(cBaseComponent):
    """
    Klasse cSourceAndSink: alternativer Betrieb als Quelle oder Senke
    """
    # source : cFlow
    # sink   : cFlow

    new_init_args = [cArg('label', 'param', 'str', 'Bezeichnung'),
                     cArg('source', 'flow', 'flow', 'flow-output Quelle'),
                     cArg('sink  ', 'flow', 'flow', 'flow-input  Senke')]

    not_used_args = ['label']

    def __init__(self, label, source, sink, **kwargs):
        """
        Konstruktor für Instanzen der Klasse cSourceAndSink

        :param label:
        :param source:
        :param sink:
        :param kwargs:
        """
        super().__init__(label, **kwargs)
        self.source = source
        self.sink = sink
        self.outputs.append(source)  # ein Output-Flow
        self.inputs.append(sink)

        # Erzwinge die Erstellung der On-Variablen, da notwendig für gleichung
        self.source.activateOnValue()
        self.sink.activateOnValue()

        self.featureAvoidInAndOutAtOnce = cFeatureAvoidFlowsAtOnce('sinkOrSource', self, [self.source, self.sink])

    def declareVarsAndEqs(self, modBox):
        """
        Deklarieren von Variablen und Gleichungen

        :param modBox:
        :return:
        """
        super().declareVarsAndEqs(modBox)

    def doModeling(self, modBox, timeIndexe):
        """
        Durchführen der Modellierung?

        :param modBox:
        :param timeIndexe:
        :return:
        """
        super().doModeling(modBox, timeIndexe)
        # Entweder Sink-Flow oder Source-Flow aktiv. Nicht beide Zeitgleich!
        self.featureAvoidInAndOutAtOnce.doModeling(modBox, timeIndexe)


class cSource(cBaseComponent):
    """
    Klasse cSource
    """
    new_init_args = [cArg('label', 'param', 'str', 'Bezeichnung'),
                     cArg('source', 'flow', 'flow', 'flow-output Quelle')]
    not_used_args = ['label']

    def __init__(self, label, source, **kwargs):
        """
        Konstruktor für Instanzen der Klasse cSource

        :param str label: Bezeichnung
        :param cFlow source: flow-output Quelle
        :param kwargs:
        """
        super().__init__(label, **kwargs)
        self.source = source
        self.outputs.append(source)  # ein Output-Flow


class cSink(cBaseComponent):
    """
    Klasse cSink
    """
    new_init_args = [cArg('label', 'param', 'str', 'Bezeichnung'),
                     cArg('sink', 'flow', 'flow', 'flow-input Senke')]

    not_used_args = ['label']

    def __init__(self, label, sink, **kwargs):
        """
        Konstruktor für Instanzen der Klasse cSink

        :param str label: Bezeichnung
        :param cFlow sink: flow-input Senke
        :param kwargs:
        """
        super().__init__(label)
        self.sink = sink
        self.inputs.append(sink)  # ein Input-Flow