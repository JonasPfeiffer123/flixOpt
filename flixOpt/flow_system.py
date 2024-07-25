# -*- coding: utf-8 -*-
"""
Created on Wed Dec 16 12:40:23 2020
developed by Felix Panitz* and Peter Stange*
* at Chair of Building Energy Systems and Heat Supply, Technische Universität Dresden
"""

import math
import time
import textwrap
import pprint
from typing import List, Set, Tuple, Dict, Union, Optional, Literal, TYPE_CHECKING
import logging

import numpy as np
import yaml  # (für json-Schnipsel-print)

from flixOpt import flixOptHelperFcts as helpers
from flixOpt.math_modeling import Variable
from flixOpt.core import TimeSeries
from flixOpt.structure import Element, SystemModel
from flixOpt.elements import Bus, Flow, Effect, EffectCollection, Component, Objective
if TYPE_CHECKING:  # for type checking and preventing circular imports
    from features import FeatureInvest
    from flixOpt.elements import Flow, Effect

log = logging.getLogger(__name__)


class FlowSystem:
    """
    A FlowSystem holds Elements (Components, Buses, Flows, Effects,...).
    """

    @property
    def elements_of_first_layer_wo_flows(self) -> List[Element]:
        return (self.components + list(self.buses) + [self.objective, self.effect_collection] +
                list(self.other_elements))

    @property
    def elements_of_fists_layer(self) -> List[Element]:
        return self.elements_of_first_layer_wo_flows + list(self.flows)

    @property
    def invest_features(self) -> List['FeatureInvest']:
        all_invest_features = []

        def get_invest_features_of_element(element: Element) -> List['FeatureInvest']:
            invest_features = []
            from flixOpt.features import FeatureInvest
            for aSubComp in element.all_sub_elements:
                if isinstance(aSubComp, FeatureInvest):
                    invest_features.append(aSubComp)
                invest_features += get_invest_features_of_element(aSubComp)  # recursive!
            return invest_features

        for element in self.elements_of_fists_layer:  # kann in Komponente (z.B. Speicher) oder Flow stecken
            all_invest_features += get_invest_features_of_element(element)

        return all_invest_features

    # Achtung: Funktion wird nicht nur für Getter genutzt.
    @property
    def flows(self) -> Set[Flow]:
        return {flow for comp in self.components for flow in comp.inputs + comp.outputs}

    # get all TS in one list:
    @property
    def all_time_series_in_elements(self) -> List[TimeSeries]:
        element: Element
        all_TS = []
        for element in self.elements_of_fists_layer:
            all_TS += element.TS_list
        return all_TS

    @property
    def buses(self) -> Set[Bus]:
        return {flow.bus for flow in self.flows}

    def __init__(self,
                 time_series: np.ndarray[np.datetime64],
                 last_time_step_hours: Optional[Union[int, float]] = None):
        """
          Parameters
          ----------
          time_series : np.ndarray of datetime64
              timeseries of the data
          last_time_step_hours : for calc
              The duration of last time step.
              Storages needs this time-duration for calculation of charge state
              after last time step.
              If None, then last time increment of time_series is used.
        """
        self.time_series = time_series
        self.last_time_step_hours = last_time_step_hours

        self.time_series_with_end = helpers.get_time_series_with_end(time_series, last_time_step_hours)
        helpers.check_time_series('global esTimeSeries', self.time_series_with_end)

        # defaults:
        self.components: List[Component] = []
        self.other_elements: Set[Element] = set()  ## hier kommen zusätzliche Elements rein, z.B. aggregation
        self.effect_collection: EffectCollection = EffectCollection('Effects')  # Kosten, CO2, Primärenergie, ...
        self.temporary_elements = []  # temporary elements, only valid for one calculation (i.g. aggregation modeling)
        # instanzieren einer globalen Komponente (diese hat globale Gleichungen!!!)
        self.objective = Objective('Objective')
        self._finalized = False  # wenn die Elements alle finalisiert sind, dann True
        self.model: Optional[SystemModel] = None  # later activated

    def __repr__(self):
        return f"<{self.__class__.__name__} with {len(self.components)} components and {len(self.effect_collection.effects)} effects>"

    def __str__(self):
        components = '\n'.join(component.__str__() for component in
                               sorted(self.components, key=lambda component: component.label.upper()))
        effects = '\n'.join(effect.__str__() for effect in
                               sorted(self.effect_collection.effects, key=lambda effect: effect.label.upper()))
        return f"FlowSystem with components:\n{components}\nand effects:\n{effects}"

    # Effekte registrieren:
    def add_effects(self, *args: Effect) -> None:
        for new_effect in list(args):
            print('Register new effect ' + new_effect.label)
            self.effect_collection.add_effect(new_effect)

    def add_components(self, *args: Component) -> None:
        # Komponenten registrieren:
        new_components = list(args)
        for new_component in new_components:
            print('Register new Component ' + new_component.label)
            self._check_if_element_is_unique(new_component, self.components)   # check if already exists:
            new_component.register_component_in_flows()   # Komponente in Flow registrieren
            new_component.register_flows_in_bus()   # Flows in Bus registrieren:
        self.components.extend(new_components)   # Add to existing list of components

        # Element registrieren ganz allgemein:

    def add_elements(self, *args: Element) -> None:
        '''
        add all modeling elements, like storages, boilers, heatpumps, buses, ...

        Parameters
        ----------
        *args : childs of   Element like cBoiler, HeatPump, Bus,...
            modeling Elements

        '''

        for new_element in list(args):
            if isinstance(new_element, Component):
                self.add_components(new_element)
            elif isinstance(new_element, Effect):
                self.add_effects(new_element)
            elif isinstance(new_element, Element):
                # check if already exists:
                self._check_if_element_is_unique(new_element, self.other_elements)
                # register Element:
                self.other_elements.add(new_element)
            else:
                raise Exception('argument is not instance of a modeling Element (Element)')

    def add_temporary_elements(self, *args: Element) -> None:
        '''
        add temporary modeling elements, only valid for one calculation,
        i.g. AggregationModeling-Element

        Parameters
        ----------
        *args : Element
            temporary modeling Elements.

        '''

        self.add_elements(*args)
        self.temporary_elements += args  # Register temporary Elements

    def delete_temporary_elements(self):  # function just implemented, still not used
        '''
        deletes all registered temporary Elements
        '''
        for temporary_element in self.temporary_elements:
            # delete them again in the lists:
            self.components.remove(temporary_element)
            self.buses.remove(temporary_element)
            self.other_elements.remove(temporary_element)
            self.effects.remove(temporary_element)
            self.flows(temporary_element)

    def _check_if_element_is_unique(self, element: Element, existing_elements: List[Element]) -> None:
        '''
        checks if element or label of element already exists in list

        Parameters
        ----------
        aElement : Element
            new element to check
        existing_elements : list
            list of already registered elements
        '''

        # check if element is already registered:
        if element in existing_elements:
            raise Exception('Element \'' + element.label + '\' already added to cEnergysystem!')

        # check if name is already used:
        # TODO: Check all elements instead of only a list that is passed?
        # TODO: An Effect with the same label as another element is not allowed, or is it?
        if element.label in [elem.label for elem in existing_elements]:
            raise Exception('Elementname \'' + element.label + '\' already used in another element!')

    def _plausibility_checks(self) -> None:
        # Check circular loops in effects: (Effekte fügen sich gegenseitig Shares hinzu):

        def error_str(effect_label: str, shareEffect_label: str):
            return (
                f'  {effect_label} -> has share in: {shareEffect_label}\n'
                f'  {shareEffect_label} -> has share in: {effect_label}'
            )

        for effect in self.effect_collection.effects:
            # operation:
            for shareEffect in effect.specific_share_to_other_effects_operation.keys():
                # Effekt darf nicht selber als Share in seinen ShareEffekten auftauchen:
                assert (effect not in shareEffect.specific_share_to_other_effects_operation.keys(),
                        f'Error: circular operation-shares \n{error_str(effect.label, shareEffect.label)}')
            # invest:
            for shareEffect in effect.specific_share_to_other_effects_invest.keys():
                assert (effect not in shareEffect.specific_share_to_other_effects_invest.keys(),
                        f'Error: circular invest-shares \n{error_str(effect.label, shareEffect.label)}')

    # Finalisieren aller ModelingElemente (dabei werden teilweise auch noch sub_elements erzeugt!)
    def finalize(self) -> None:
        print('finalize all Elements...')
        self._plausibility_checks()
        # nur EINMAL ausführen: Finalisieren der Elements:
        if not self._finalized:
            # finalize Elements for modeling:
            for element in self.elements_of_fists_layer:
                print(element.label)   #TODO: Remove this print??
                element.finalize()  # inklusive sub_elements!
            self._finalized = True

    def do_modeling_of_elements(self) -> SystemModel:

        if not self._finalized:
            raise Exception('modeling not possible, because Energysystem is not finalized')

        # Bus-Liste erstellen: -> Wird die denn überhaupt benötigt?

        # TODO: Achtung time_indices kann auch nur ein Teilbereich von time_indices abdecken, z.B. wenn man für die anderen Zeiten anderweitig modellieren will
        # --> ist aber nicht sauber durchimplementiert in den ganzehn add_summand()-Befehlen!!
        time_indices = range(len(self.model.time_indices))

        self.effect_collection.declare_vars_and_eqs(self.model)
        self.effect_collection.do_modeling(self.model, time_indices)
        self.objective.declare_vars_and_eqs(self.model)
        self.objective.add_objective_effect_and_penalty(self.effect_collection)

        # Komponenten-Modellierung (# inklusive sub_elements!)
        for aComp in self.components:
            aComp: Component
            log.debug('model ' + aComp.label + '...')
            # todo: ...OfFlows() ist nicht schön --> besser als rekursive Geschichte aller subModelingElements der Komponente umsetzen z.b.
            aComp.declare_vars_and_eqs_of_flows(self.model)
            aComp.declare_vars_and_eqs(self.model)

            aComp.do_modeling_of_flows(self.model, time_indices)
            aComp.do_modeling(self.model, time_indices)

            aComp.add_share_to_globals_of_flows(self.effect_collection, self.model)
            aComp.add_share_to_globals(self.effect_collection, self.model)

        # Bus-Modellierung (# inklusive sub_elements!)
        aBus: Bus
        for aBus in self.buses:
            log.debug('model ' + aBus.label + '...')
            aBus.declare_vars_and_eqs(self.model)
            aBus.do_modeling(self.model, time_indices)
            aBus.add_share_to_globals(self.effect_collection, self.model)

        # TODO: Currently there are no "other elements"
        # weitere übergeordnete Modellierungen:
        for element in self.other_elements:
            element.declare_vars_and_eqs(self.model)
            element.do_modeling(self.model, time_indices)
            element.add_share_to_globals(self.effect_collection, self.model)

        return self.model

    def transform_to_math_model(self):
        self.model.to_math_model()

    # aktiviere in TS die gewählten Indexe: (wird auch direkt genutzt, nicht nur in activate_system_model)
    def activate_indices_in_time_series(
            self, indices: Union[List[int], range],
            alternative_data_for_time_series: Optional[Dict[TimeSeries, np.ndarray]] = None) -> None:
        # TODO: Aggreagation functionality to other part of framework?
        aTS: TimeSeries
        if alternative_data_for_time_series is None:
            alternative_data_for_time_series = {}

        for aTS in self.all_time_series_in_elements:
            # Wenn explicitData vorhanden:
            if aTS in alternative_data_for_time_series.keys():
                explicitData = alternative_data_for_time_series[aTS]
            else:
                explicitData = None
                # Aktivieren:
            aTS.activate(indices, explicitData)

    def activate_model(self, system_model: SystemModel) -> None:
        self.model = system_model
        system_model: SystemModel
        element: Element

        # hier nochmal TS updaten (teilweise schon für Preprozesse gemacht):
        self.activate_indices_in_time_series(system_model.time_indices, system_model.TS_explicit)

        # Wenn noch nicht gebaut, dann einmalig Element.model bauen:
        if system_model.models_of_elements == {}:
            log.debug('create model-Vars for Elements of EnergySystem')
            for element in self.elements_of_fists_layer:
                # BEACHTE: erst nach finalize(), denn da werden noch sub_elements erst erzeugt!
                if not self._finalized:
                    raise Exception('activate_model(): --> Geht nicht, da FlowSystem noch nicht finalized!')
                # model bauen und in model registrieren.
                element.create_new_model_and_activate_system_model(self.model)  # inkl. sub_elements
        else:
            # nur Aktivieren:
            for element in self.elements_of_fists_layer:
                element.activate_system_model(system_model)  # inkl. sub_elements

    # ! nur nach Solve aufrufen, nicht später nochmal nach activating model (da evtl stimmen Referenzen nicht mehr unbedingt!)
    def get_results_after_solve(self) -> Tuple[Dict, Dict]:
        results = {}  # Daten
        results_var = {}  # zugehörige Variable
        # für alle Komponenten:
        for element in self.elements_of_first_layer_wo_flows:
            # results        füllen:
            (results[element.label], results_var[element.label]) = element.get_results()  # inklusive sub_elements!

        # Zeitdaten ergänzen
        aTime = {}
        results['time'] = aTime
        aTime['time_series_with_end'] = self.model.time_series_with_end
        aTime['time_series'] = self.model.time_series
        aTime['dt_in_hours'] = self.model.dt_in_hours
        aTime['dt_in_hours_total'] = self.model.dt_in_hours_total

        return results, results_var

    def printModel(self) -> None:
        aBus: Bus
        aComp: Component
        print('')
        print('##############################################################')
        print('########## Short String Description of Energysystem ##########')
        print('')

        print(yaml.dump(self.description_of_system()))

    def description_of_system(self, flowsWithBusInfo=False) -> Dict:
        modelDescription = {}

        # Anmerkung buses und comps als dict, weil Namen eindeutig!
        # Buses:
        modelDescription['buses'] = {}
        for aBus in self.buses:
            aBus: Bus
            modelDescription['buses'].update(aBus.description())
        # Comps:
        modelDescription['components'] = {}
        aComp: Component
        for aComp in self.components:
            modelDescription['components'].update(aComp.description())

        # Flows:
        flowList = []
        modelDescription['flows'] = flowList
        aFlow: Flow
        for aFlow in self.flows:
            flowList.append(aFlow.description())

        return modelDescription

    def description_of_equations(self) -> Dict:
        aDict = {}

        # comps:
        aSubDict = {}
        aDict['Components'] = aSubDict
        aComp: Element
        for aComp in self.components:
            aSubDict[aComp.label] = aComp.description_of_equations()

        # buses:
        aSubDict = {}
        aDict['buses'] = aSubDict
        for aBus in self.buses:
            aSubDict[aBus.label] = aBus.description_of_equations()

        # Objective:
        aDict['objective'] = self.objective.description_of_equations()

        # Effects:
        aDict['effects'] = self.effect_collection.description_of_equations()

        # flows:
        aSubDict = {}
        aDict['flows'] = aSubDict
        for aComp in self.components:
            for aFlow in (aComp.inputs + aComp.outputs):
                aSubDict[aFlow.label_full] = aFlow.description_of_equations()

        # others
        aSubDict = {}
        aDict['others'] = aSubDict
        for element in self.other_elements:
            aSubDict[element.label] = element.description_of_equations()

        return aDict

    def print_equations(self) -> None:

        print('')
        print('##############################################################')
        print('################# Equations of Energysystem ##################')
        print('')

        print(yaml.dump(self.description_of_equations(),
                        default_flow_style=False,
                        allow_unicode=True))

    def description_of_variables(self, structured=True) -> Union[List, Dict]:
        aVar: Variable

        # liste:
        if not structured:
            aList = []
            for aVar in self.model.variables:
                aList.append(aVar.get_str_description())
            return aList

        # struktur:
        else:
            aDict = {}

            # comps (and belonging flows):
            subDict = {}
            aDict['Comps'] = subDict
            # comps:
            for aComp in self.components:
                subDict[aComp.label] = aComp.description_of_variables()
                for aFlow in aComp.inputs + aComp.outputs:
                    subDict[aComp.label] += aFlow.description_of_variables()

            # buses:
            subDict = {}
            aDict['buses'] = subDict
            for bus in self.buses:
                subDict[bus.label] = bus.description_of_variables()

            # Objective:
            aDict['objective'] = self.objective.description_of_variables()

            # Effects:
            aDict['effects'] = self.effect_collection.description_of_variables()

            # others
            aSubDict = {}
            aDict['others'] = aSubDict
            for element in self.other_elements:
                aSubDict[element.label] = element.description_of_variables()

            return aDict

    def print_variables(self) -> None:
        print('')
        print('##############################################################')
        print('################# Variables of Energysystem ##################')
        print('')
        print('############# a) as list : ################')
        print('')

        yaml.dump(self.description_of_variables(structured=False))

        print('')
        print('############# b) structured : ################')
        print('')

        yaml.dump(self.description_of_variables(structured=True))

    # Datenzeitreihe auf Basis gegebener time_indices aus globaler extrahieren:
    def get_time_data_from_indices(self, time_indices: Union[List[int], range]) -> Tuple[
                                                                                        np.ndarray[np.datetime64],
                                                                                        np.ndarray[np.datetime64],
                                                                                        np.ndarray[np.float64],
                                                                                        np.float64]:
        # if time_indices is None, dann alle : time_indices = range(length(self.time_series))
        # Zeitreihen:
        time_series = self.time_series[time_indices]
        # next timestamp as endtime:
        endTime = self.time_series_with_end[time_indices[-1] + 1]
        time_series_with_end = np.append(time_series, endTime)

        # Zeitdifferenz:
        #              zweites bis Letztes            - erstes bis Vorletztes
        dt = time_series_with_end[1:] - time_series_with_end[0:-1]
        dt_in_hours = dt / np.timedelta64(1, 'h')
        # dt_in_hours    = dt.total_seconds() / 3600
        dt_in_hours_total = sum(dt_in_hours)  # Gesamtzeit
        return (time_series, time_series_with_end, dt_in_hours, dt_in_hours_total)