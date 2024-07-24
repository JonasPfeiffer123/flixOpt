# -*- coding: utf-8 -*-
"""
Created on Wed Dec 16 12:40:23 2020
developed by Felix Panitz* and Peter Stange*
* at Chair of Building Energy Systems and Heat Supply, Technische Universität Dresden
"""

import datetime
import logging
import math
import pathlib
import timeit
from typing import List, Dict, Optional, Literal, Tuple, Union

import numpy as np

from flixOpt import flixOptHelperFcts as helpers
from flixOpt.aggregation import TimeSeriesCollection
from flixOpt.core import Skalar
from flixOpt.flixBasicsPublic import TimeSeriesRaw
from flixOpt.modeling import VariableTS
from flixOpt.structure import SystemModel
from flixOpt.system import System

log = logging.getLogger(__name__)


class Calculation:
    """
    class for defined way of solving a energy system optimizatino
    """

    @property
    def infos(self):
        infos = {}

        calcInfos = self._infos
        infos['calculation'] = calcInfos
        calcInfos['name'] = self.name
        calcInfos['no ChosenIndexe'] = len(self.time_indices)
        calcInfos['calculation_type'] = self.__class__.__name__
        calcInfos['duration'] = self.durations
        infos['system_description'] = self.system.description_of_system()
        infos['system_models'] = {}
        infos['system_models']['duration'] = [system_model.duration for system_model in self.system_models]
        infos['system_models']['info'] = [system_model.infos for system_model in self.system_models]

        return infos

    @property
    def results(self):
        # wenn noch nicht belegt, dann aus system_model holen
        if self._results is None:
            self._results = self.system_models[0].results  # (bei segmented Calc ist das schon explizit belegt.)
        return self._results

    @property
    def results_struct(self):
        raise NotImplementedError()

    # time_indices: die Indexe des Energiesystems, die genutzt werden sollen. z.B. [0,1,4,6,8]
    def __init__(self, name, system: System, modeling_language: Literal["pyomo", "cvxpy"],
                 time_indices: Optional[list[int]] = None):
        """
        Parameters
        ----------
        name : str
            name of calculation
        system : System
            system which should be calculated
        modeling_language : 'pyomo','cvxpy' (not implemeted yet)
            choose optimization modeling language
        time_indices : None, list
            list with indexe, which should be used for calculation. If None, then all timesteps are used.
        """
        self.name = name
        self.system = system
        self.modeling_language = modeling_language
        self.time_indices = time_indices
        self._infos = {}

        self.system_models: List[SystemModel] = []
        self.durations = {'modeling': 0, 'solving': 0}  # Dauer der einzelnen Dinge

        self.time_indices = time_indices or range(len(system.time_series))  # Wenn time_indices = None, dann alle nehmen
        (self.time_series, self.time_series_with_end, self.dt_in_hours, self.dt_in_hours_total) = (
            system.get_time_data_from_indices(self.time_indices))
        helpers.check_time_series('time_indices', self.time_series)

        self._paths = {'log': None, 'data': None, 'info': None}
        self._results = None
        self._results_struct = None  # hier kommen die verschmolzenen Ergebnisse der Segmente rein!

    def _define_path_names(self, path: str, save_results: bool, include_timestamp: bool = True,
                           nr_of_system_models: int = 1):
        """
        Creates the path for saving results and alters the name of the calculation to have a timestamp
        """
        if include_timestamp:
            timestamp = datetime.datetime.now()
            timestring = timestamp.strftime('%Y-%m-%data')
            self.name = f'{timestring}_{self.name.replace(" ", "")}'

        if save_results:
            path = pathlib.Path.cwd() / path  # absoluter Pfad:
            path.mkdir(parents=True, exist_ok=True)  # Pfad anlegen, fall noch nicht vorhanden:

            self._paths["log"] = [path / f'{self.name}_solver_{i}.log' for i in range(nr_of_system_models)]
            self._paths["data"] = path / f'{self.name}_data.pickle'
            self._paths["info"] = path / f'{self.name}_solvingInfos.yaml'

    def check_if_already_modeled(self):
        if self.system.temporary_elements:  # if some element in this list
            raise Exception(f'The Energysystem has some temporary modelingElements from previous calculation '
                            f'(i.g. aggregation-Modeling-Elements. These must be deleted before new calculation.')

    def _save_solve_infos(self):
        import yaml
        # Daten:
        # with open(yamlPath_Data, 'w') as f:
        #   yaml.dump(self.results, f, sort_keys = False)
        import pickle
        with open(self._paths['data'], 'wb') as f:
            pickle.dump(self.results, f, protocol=pickle.HIGHEST_PROTOCOL)

        # Infos:'
        with open(self._paths['info'], 'w', encoding='utf-8') as f:
            yaml.dump(self.infos, f, width=1000,  # Verhinderung Zeilenumbruch für lange equations
                      allow_unicode=True, sort_keys=False)

        aStr = f'# saved calculation {self.name} #'
        print('#' * len(aStr))
        print(aStr)
        print('#' * len(aStr))


class FullCalculation(Calculation):
    """
    class for defined way of solving a energy system optimization
    """

    def do_modeling(self) -> SystemModel:
        self.check_if_already_modeled()
        self.system.finalize()  # System finalisieren:

        t_start = timeit.default_timer()
        system_model = SystemModel(self.name, self.modeling_language, self.system, self.time_indices)
        self.system.activate_model(system_model)  # model aktivieren:
        self.system.do_modeling_of_elements()  # modellieren:

        self.system_models.append(system_model)
        self.durations['modeling'] = round(timeit.default_timer() - t_start, 2)
        return system_model

    def solve(self, solverProps: dict, path='results/', save_results=True):
        self._define_path_names(path, save_results, nr_of_system_models=1)
        self.system_models[0].solve(**solverProps, logfile_name=self._paths['log'][0])

        if save_results:
            self._save_solve_infos()


class AggregatedCalculation(Calculation):
    """
    class for defined way of solving a energy system optimizatino
    """

    def __init__(self, name: str, system: System, modeling_language: Literal["pyomo", "cvxpy"],
                 time_indices: Optional[list[int]] = None):
        """
        Parameters
        ----------
        name : str
            name of calculation
        system : System
            system which should be calculated
        modeling_language : 'pyomo','cvxpy' (not implemeted yet)
            choose optimization modeling language
        time_indices : None, list
            list with indexe, which should be used for calculation. If None, then all timesteps are used.
        """
        super().__init__(name, system, modeling_language, time_indices)
        self.time_series_for_aggregation = None
        self.aggregation_data = None
        self.time_series_collection: Optional[TimeSeriesCollection] = None

    def do_modeling(self, periodLengthInHours, nr_of_typical_periods, use_extreme_periods, fix_storage_flows,
                    fix_binary_vars_only, percentage_of_period_freedom=0, costs_of_period_freedom=0, addPeakMax=None,
                    addPeakMin=None):
        """
        method of aggregated modeling.
        1. Finds typical periods.
        2. Equalizes variables of typical periods.

        Parameters
        ----------
        periodLengthInHours : float
            length of one period.
        nr_of_typical_periods : int
            no of typical periods
        use_extreme_periods : boolean
            True, if periods of extreme values should be explicitly chosen
            Define recognised timeseries in args addPeakMax, addPeakMin!
        fix_storage_flows : boolean
            Defines, wether load- and unload-Flow should be also aggregated or not.
            If all other flows are fixed, it is mathematically not necessary
            to fix them.
        fix_binary_vars_only : boolean
            True, if only binary var should be aggregated.
            Additionally choose, wether orginal or aggregated timeseries should
            be chosen for the calculation.
        percentage_of_period_freedom : 0...100
            Normally timesteps of all periods in one period-collection
            are all equalized. Here you can choose, which percentage of values
            can maximally deviate from this and be "free variables". The solver
            chooses the "free variables".
        costs_of_period_freedom : float
            costs per "free variable". The default is 0.
            !! Warning: At the moment these costs are allocated to
            operation costs, not to penalty!!
        useOriginalTimeSeries : boolean.
            orginal or aggregated timeseries should
            be chosen for the calculation. default is False.
        addPeakMax : list of TimeSeriesRaw
            list of data-timeseries. The period with the max-value are
            chosen as a explicitly period.
        addPeakMin : list of TimeSeriesRaw
            list of data-timeseries. The period with the min-value are
            chosen as a explicitly period.


        Returns
        -------
        system_model : TYPE
            DESCRIPTION.

        """

        addPeakMax = addPeakMax or []
        addPeakMin = addPeakMin or []
        self.check_if_already_modeled()

        self._infos['aggregatedProps'] = {'periodLengthInHours': periodLengthInHours,
                                          'nr_of_typical_periods': nr_of_typical_periods,
                                          'use_extreme_periods': use_extreme_periods,
                                          'fix_storage_flows': fix_storage_flows,
                                          'fix_binary_vars_only': fix_binary_vars_only,
                                          'percentage_of_period_freedom': percentage_of_period_freedom,
                                          'costs_of_period_freedom': costs_of_period_freedom}

        t_start_agg = timeit.default_timer()
        # chosen Indexe aktivieren in TS: (sonst geht Aggregation nicht richtig)
        self.system.activate_indices_in_time_series(self.time_indices)

        # Zeitdaten generieren:
        (chosenTimeSeries, chosenTimeSeriesWithEnd, dt_in_hours, dt_in_hours_total) = (
            self.system.get_time_data_from_indices(self.time_indices))

        # check equidistant timesteps:
        if max(dt_in_hours) - min(dt_in_hours) != 0:
            raise Exception('!!! Achtung Aggregation geht nicht, da unterschiedliche delta_t von ' + str(
                min(dt_in_hours)) + ' bis ' + str(max(dt_in_hours)) + ' h')

        print('#########################')
        print('## TS for aggregation ###')

        ## Daten für Aggregation vorbereiten:
        # TSlist and TScollection ohne Skalare:
        self.time_series_for_aggregation = [item for item in self.system.all_time_series_in_elements if item.is_array]
        self.time_series_collection = TimeSeriesCollection(self.time_series_for_aggregation,
                                                           addPeakMax_TSraw=addPeakMax, addPeakMin_TSraw=addPeakMin, )

        self.time_series_collection.print()

        import pandas as pd
        # seriesDict = {i : self.time_series_for_aggregation[i].active_data_vector for i in range(length(self.time_series_for_aggregation))}
        df_OriginalData = pd.DataFrame(self.time_series_collection.seriesDict,
                                       index=chosenTimeSeries)  # eigentlich wäre TS als column schön, aber TSAM will die ordnen können.

        # Check, if timesteps fit in Period:
        stepsPerPeriod = periodLengthInHours / self.dt_in_hours[0]
        if not stepsPerPeriod.is_integer():
            raise Exception('Fehler! Gewählte Periodenlänge passt nicht zur Zeitschrittweite')

        ##########################################################
        # ### Aggregation - creation of aggregated timeseries: ###
        from flixOpt import aggregation as flixAgg
        dataAgg = flixAgg.Aggregation('aggregation', timeseries=df_OriginalData,
                                      hours_per_time_step=self.dt_in_hours[0], hours_per_period=periodLengthInHours,
                                      hasTSA=False, nr_of_typical_periods=nr_of_typical_periods,
                                      use_extreme_periods=use_extreme_periods,
                                      weights=self.time_series_collection.weightDict,
                                      addPeakMax=self.time_series_collection.addPeak_Max_labels,
                                      addPeakMin=self.time_series_collection.addPeak_Min_labels)

        dataAgg.cluster()
        self.aggregation_data = dataAgg

        self._infos['aggregatedProps']['periods_order'] = str(list(dataAgg.aggregation.clusterOrder))

        # aggregation_data.aggregation.clusterPeriodIdx
        # aggregation_data.aggregation.clusterOrder
        # aggregation_data.aggregation.clusterPeriodNoOccur
        # aggregation_data.aggregation.predictOriginalData()
        # self.periods_order = aggregation.clusterOrder
        # self.period_occurrences = aggregation.clusterPeriodNoOccur

        # ### Some plot for plausibility check ###

        import matplotlib.pyplot as plt
        plt.figure(figsize=(8, 6))
        plt.title('aggregated series (dashed = aggregated)')
        plt.plot(df_OriginalData.values)
        for label_TS, agg_values in dataAgg.results.items():
            # aLabel = str(i)
            # aLabel = self.time_series_for_aggregation[i].label_full
            plt.plot(agg_values.values, '--', label=label_TS)
        if len(self.time_series_for_aggregation) < 10:  # wenn nicht zu viele
            plt.legend(bbox_to_anchor=(0.5, -0.05), loc='upper center')
        plt.show()

        # ### Some infos as print ###

        print('TS Aggregation:')
        for i in range(len(self.time_series_for_aggregation)):
            aLabel = self.time_series_for_aggregation[i].label_full
            print('TS ' + str(aLabel))
            print('  max_agg:' + str(max(dataAgg.results[aLabel])))
            print('  max_orig:' + str(max(df_OriginalData[aLabel])))
            print('  min_agg:' + str(min(dataAgg.results[aLabel])))
            print('  min_orig:' + str(min(df_OriginalData[aLabel])))
            print('  sum_agg:' + str(sum(dataAgg.results[aLabel])))
            print('  sum_orig:' + str(sum(df_OriginalData[aLabel])))

        print('addpeakmax:')
        print(self.time_series_collection.addPeak_Max_labels)
        print('addpeakmin:')
        print(self.time_series_collection.addPeak_Min_labels)

        # ################
        # ### Modeling ###

        aggregationModel = flixAgg.AggregationModeling('aggregation', self.system,
                                                       index_vectors_of_clusters=dataAgg.index_vectors_of_clusters,
                                                       fix_binary_vars_only=fix_binary_vars_only,
                                                       fix_storage_flows=fix_storage_flows, elements_to_clusterize=None,
                                                       percentage_of_period_freedom=percentage_of_period_freedom,
                                                       costs_of_period_freedom=costs_of_period_freedom)

        # temporary Modeling-Element for equalizing indices of aggregation:
        self.system.add_temporary_elements(aggregationModel)

        if fix_binary_vars_only:
            TS_explicit = None
        else:
            # neue (Explizit)-Werte für TS sammeln::
            TS_explicit = {}
            for i in range(len(self.time_series_for_aggregation)):
                TS = self.time_series_for_aggregation[i]
                # todo: agg-Wert für TS:
                TS_explicit[TS] = dataAgg.results[TS.label_full].values  # nur data-array ohne Zeit

        # ##########################
        # ## System finalizing: ##
        self.system.finalize()

        self.durations['aggregation'] = round(timeit.default_timer() - t_start_agg, 2)

        t_m_start = timeit.default_timer()
        # Modellierungsbox / TimePeriod-Box bauen: ! inklusive TS_explicit!!!
        system_model = SystemModel(self.name, self.modeling_language, self.system, self.time_indices,
                                   TS_explicit)  # alle Indexe nehmen!
        self.system_models.append(system_model)
        # model aktivieren:
        self.system.activate_model(system_model)
        # modellieren:
        self.system.do_modeling_of_elements()

        self.durations['modeling'] = round(timeit.default_timer() - t_m_start, 2)
        return system_model

    def solve(self, solverProps: dict, path='results/', save_results=True):
        self._define_path_names(path, save_results, nr_of_system_models=1)
        self.system_models[0].solve(**solverProps, logfile_name=self._paths['log'][0])

        if save_results:
            self._save_solve_infos()


class SegmentedCalculation(Calculation):
    """
    class for defined way of solving a energy system optimizatino
    """

    @property
    def results_struct(self):
        # Wenn noch nicht ermittelt:
        if self._results_struct is None:
            self._results_struct = helpers.createStructFromDictInDict(self.results)
        return self._results_struct

    def solve(self, solverProps, segment_length: int, nr_of_used_steps: int, path='results/'):
        """
        Dividing and Modeling the problem in (overlapped) time-segments.
        Storage values as result of segment n are overtaken
        to the next segment n+1 for timestep, which is first in segment n+1

        Afterwards timesteps of segments (without overlap)
        are put together to the full timeseries

        Because the result of segment n is used in segment n+1, modeling and
        solving is both done in this method

        Take care:
        Parameters like invest_parameters, loadfactor etc. does not make sense in
        segmented modeling, cause they are newly defined in each segment

        Parameters
        ----------
        solverProps : TYPE
            DESCRIPTION.
        segment_length : int
            nr Of Timesteps of Segment.
        nr_of_used_steps : int
            nr of timesteps used/overtaken in resulting complete timeseries
            (the timesteps after these are "overlap" and used for better
            results of chargestate of storages)
        path : str
            path for output. The default is 'results/'.

        """
        self.check_if_already_modeled()
        self._infos['segmented_properties'] = {'segment_length': segment_length, 'nr_of_used_steps': nr_of_used_steps}
        print('##############################################################')
        print('#################### segmented Solving #######################')

        t_start = timeit.default_timer()
        self.system.finalize()   # system finalisieren:

        assert len(self.system.invest_features) == 0, 'Invest-Parameters not supported in segmented calculation!'
        assert nr_of_used_steps <= segment_length
        assert segment_length <= len(self.time_series), f'{segment_length=} cant be greater than {len(self.time_series)=}'

        # Anzahl = Letzte Simulation bis zum Ende plus die davor mit Überlappung:
        nr_of_segments = math.ceil((len(self.time_series)) / nr_of_used_steps)
        self._infos['segmented_properties']['nr_of_segments'] = nr_of_segments
        print(f'Indices       : {self.time_indices[0]}...{self.time_indices[-1]}')
        print(f'Segment Length: {segment_length}')
        print(f'Used Steps    : {nr_of_used_steps}')
        print(f'Number of Segments: {nr_of_segments}\n')

        self._define_path_names(path, save_results=True, nr_of_system_models=nr_of_segments)

        for i in range(nr_of_segments):
            start_index_of_segment = i * nr_of_used_steps
            end_index_of_segment = min(start_index_of_segment + segment_length, len(self.time_indices)) - 1

            start_index_global = self.time_indices[start_index_of_segment]
            end_index_global = self.time_indices[end_index_of_segment]  # inklusiv
            indices_global = self.time_indices[start_index_of_segment:end_index_of_segment + 1]  # inklusive endIndex

            # new real_nr_of_used_steps:
            if i == max(range(nr_of_segments)):   # if last Segment:
                nr_of_used_steps = end_index_of_segment - start_index_of_segment + 1

            print(f'{i}. Segment (system indices {start_index_global}...{end_index_global}):')


            # Modellierungsbox / TimePeriod-Box bauen:
            system_model_of_segment = SystemModel(f'{self.name}_seg{i}', self.modeling_language, self.system,
                                        indices_global)  # alle Indexe nehmen!

            # Startwerte übergeben von Vorgänger-system_model:
            if i > 0:
                system_model_of_prior_segment = self.system_models[i - 1]
                system_model_of_segment.before_values = BeforeValues(system_model_of_prior_segment.all_ts_variables,
                                                           nr_of_used_steps - 1)
                print('### before_values: ###')
                system_model_of_segment.before_values.print()
                print('#######################')  # transferStartValues(segment, segmentBefore)

            # model in Energiesystem aktivieren:
            self.system.activate_model(system_model_of_segment)

            # modellieren:
            t_start_modeling = timeit.default_timer()
            self.system.do_modeling_of_elements()
            self.durations['modeling'] += round(timeit.default_timer() - t_start_modeling, 2)
            # system_model in Liste hinzufügen:
            self.system_models.append(system_model_of_segment)

            # Lösen:
            t_start_solving = timeit.default_timer()

            system_model_of_segment.solve(**solverProps,
                                logfile_name=self._paths['log'][i])  # keine SolverOutput-Anzeige, da sonst zu viel
            self.durations['solving'] += round(timeit.default_timer() - t_start_solving, 2)
            ## results adding:
            self._add_segment_results(system_model_of_segment, start_index_of_segment, nr_of_used_steps)

        self.durations['model, solve and segmentStuff'] = round(timeit.default_timer() - t_start, 2)

        self._save_solve_infos()

    def _add_segment_results(self, segment, startIndex_calc, realNrOfUsedSteps):
        # rekursiv aufzurufendes Ergänzen der Dict-Einträge um segment-Werte:

        if (self._results is None):
            self._results = {}  # leeres Dict als Ausgangszustand

        def append_new_results_to_dict_values(result: Dict, result_to_append: Dict, result_to_append_var: Dict):
            if result == {}:
                firstFill = True  # jeweils neuer Dict muss erzeugt werden für globales Dict
            else:
                firstFill = False

            for key, val in result_to_append.items():
                # print(key)

                # Wenn val ein Wert ist:
                if isinstance(val, np.ndarray) or isinstance(val, np.float64) or np.isscalar(val):

                    # Beachte Länge (withEnd z.B. bei Speicherfüllstand)
                    if key in ['time_series', 'dt_in_hours', 'dt_in_hours_total']:
                        withEnd = False
                    elif key in ['time_series_with_end']:
                        withEnd = True
                    else:
                        # Beachte Speicherladezustand und ähnliche Variablen:
                        aReferedVariable = result_to_append_var[key]
                        aReferedVariable: VariableTS
                        withEnd = isinstance(aReferedVariable, VariableTS) \
                                  and (aReferedVariable.before_value is not None) \
                                  and aReferedVariable.before_value_is_start_value

                        # nested:

                    def getValueToAppend(val, withEnd):
                        # wenn skalar, dann Vektor draus machen:
                        # todo: --> nicht so schön!
                        if np.isscalar(val):
                            val = np.array([val])

                        if withEnd:
                            if firstFill:
                                aValue = val[0:realNrOfUsedSteps + 1]  # (inklusive WithEnd!)
                            else:
                                # erstes Element weglassen, weil das schon vom Vorgängersegment da ist:
                                aValue = val[1:realNrOfUsedSteps + 1]  # (inklusive WithEnd!)
                        else:
                            aValue = val[0:realNrOfUsedSteps]  # (nur die genutzten Steps!)
                        return aValue

                    aValue = getValueToAppend(val, withEnd)

                    if firstFill:
                        result[key] = aValue
                    else:  # erstmaliges Füllen. Array anlegen.
                        result[key] = np.append(result[key], aValue)  # Anhängen (nur die genutzten Steps!)

                else:
                    if firstFill: result[key] = {}

                    if (result_to_append_var is not None) and key in result_to_append_var.keys():
                        resultToAppend_sub = result_to_append_var[key]
                    else:  # z.B. bei time (da keine Variablen)
                        resultToAppend_sub = None
                    append_new_results_to_dict_values(result[key], result_to_append[key],
                                                      resultToAppend_sub)  # hier rekursiv!

        # rekursiv:
        append_new_results_to_dict_values(self._results, segment.results, segment.results_var)

        # results füllen:  # ....


class BeforeValues:
    # managed die Before-Werte des segments:
    def __init__(self,
                 variables_ts: List[VariableTS],
                 from_index: int):
        self.beforeValues = {}
        # Sieht dann so aus = {(Element1, aVar1.name): (value, time),
        #                      (Element2, aVar2.name): (value, time),
        #                       ...                       }
        for variable in variables_ts:
            if variable.before_value is not None:
                # Before-Value holen:
                value = variable.get_before_value_for_next_segment(from_index)
                self.add_before_values(variable, value)

    def add_before_values(self, variable: VariableTS, value: Skalar):
        if variable.label_full in self.beforeValues.keys():
            raise Exception('setBeforeValues(): Achtung Wert würde überschrieben, Wert ist schon belegt!')
        else:
            self.beforeValues.update({variable.label_full: value})

    # return (value, time)
    def get_before_values(self, variable: VariableTS) -> Optional[Tuple[Union[int, float], np.datetime64]]:
        if variable.label_full in self.beforeValues.keys():
            return self.beforeValues[variable.label_full]  # returns (value, time)
        else:
            return None  # returns None if variable has no before_value

    def print(self):
        for varName in self.beforeValues.keys():
            print(varName + ' = ' + str(self.beforeValues[varName]))
