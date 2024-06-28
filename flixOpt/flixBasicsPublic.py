# -*- coding: utf-8 -*-
"""
Created on Tue Sep  6 15:25:43 2022
developed by Felix Panitz* and Peter Stange*
* at Chair of Building Energy Systems and Heat Supply, Technische Universität Dresden
"""
from typing import Union, Optional, Dict, List
import numpy as np


# Anmerkung: TimeSeriesRaw separat von TimeSeries wg. Einfachheit für Anwender
class TimeSeriesRaw:
    def __init__(self,
                 value: Union[int, float, np.ndarray],
                 agg_group: Optional[str] = None,
                 agg_weight: Optional[float] = None):
        """
        timeseries class for transmit timeseries AND special characteristics of timeseries,
        i.g. to define weights needed in calcType 'aggregated'
            EXAMPLE solar:
            you have several solar timeseries. These should not be overweighted
            compared to the remaining timeseries (i.g. heat load, price)!
            val_rel_solar1 = TimeSeriesRaw(sol_array_1, type = 'solar')
            val_rel_solar2 = TimeSeriesRaw(sol_array_2, type = 'solar')
            val_rel_solar3 = TimeSeriesRaw(sol_array_3, type = 'solar')
            --> this 3 series of same type share one weight, i.e. internally assigned each weight = 1/3
            (instead of standard weight = 1)

        Parameters
        ----------
        value : Union[int, float, np.ndarray]
            The timeseries data, which can be a scalar, array, or numpy array.
        agg_group : str, optional
            The group this TimeSeriesRaw is a part of. agg_weight is split between members of a group. Default is None.
        agg_weight : float, optional
            The weight for calcType 'aggregated', should be between 0 and 1. Default is None.

        Raises
        ------
        Exception
            If both agg_group and agg_weight are set, an exception is raised.
        """
        self.value = value
        self.agg_group = agg_group
        self.agg_weight = agg_weight
        if (agg_group is not None) and (agg_weight is not None):
            raise Exception('Either <agg_group> or explicit <agg_weigth> can be set. Not both!')

    def __repr__(self):
        return f"<cTSraw agg_group={self.agg_group!r}, agg_weight={self.agg_weight!r}>"

    def __str__(self):
        agg_info = f"agg_group={self.agg_group}, agg_weight={self.agg_weight}" if self.agg_group or self.agg_weight else "no aggregation info"
        return f"Timeseries: {agg_info}"


# Sammlung von Props für Investitionskosten (für cFeatureInvest)
class InvestParameters:
    '''
    collects arguments for invest-stuff
    '''

    def __init__(self,
                 fix_effects: Optional[Union[Dict,int, float]] = None,
                 divest_effects: Optional[Union[Dict,int, float]] = None,
                 fixed_size: bool = True,
                 optional: bool = True,  # Investition ist weglassbar
                 specific_effects: Union[Dict, int, float] = 0,  # costs per Flow-Unit/Storage-Size/...
                 effects_in_segments: Optional[Union[Dict, List]] = None,
                 minimum_size: Union[int, float] = 0,  # nur wenn nominal_val_is_fixed = False
                 maximum_size: Union[int, float] = 1e9,  # nur wenn nominal_val_is_fixed = False
                 **kwargs):
        """
        Parameters
        ----------
        fix_effects : None or scalar, optional
            Fixed investment costs if invested.
            (Attention: Annualize costs to chosen period!)
        divest_effects : None or scalar, optional
            Fixed divestment costs (if not invested, e.g., demolition costs or contractual penalty).
        fixed_size : bool, optional
            Determines if the investment size is fixed. If its not fixed, uses naminal_val as an optimization variable.
        optional : bool, optional
            If True, investment is not forced.
        specific_effects : scalar or Dict[Effect: Union[int, float, np.ndarray], optional
            Specific costs, e.g., in €/kW_nominal or €/m²_nominal.
            Example: {costs: 3, CO2: 0.3} with costs and CO2 representing an Object of class Effect
            (Attention: Annualize costs to chosen period!)
        effects_in_segments : list or List[ List[Union[int,float]], Dict[cEffecType: Union[List[Union[int,float]], optional
            Linear relation in segments [invest_segments, cost_segments].
            Example 1:
                [           [5, 25, 25, 100],       # nominal_value in kW
                 {costs:    [50,250,250,800],       # €
                  PE:       [5, 25, 25, 100]        # kWh_PrimaryEnergy
                  }
                ]
            Example 2 (if only standard-effect):
                [   [5, 25, 25, 100],  # kW # nominal_value in kW
                    [50,250,250,800]        # value for standart effect, typically €
                 ]  # €
            (Attention: Annualize costs to chosen period!)
            (Args 'specific_effects' and 'fix_effects' can be used in parallel to InvestsizeSegments)
        minimum_size : scalar
            Min nominal value (only if: nominal_val_is_fixed = False).
        maximum_size : scalar
            Max nominal value (only if: nominal_val_is_fixed = False).
        """

        self.fix_effects = fix_effects
        self.divest_effects = divest_effects
        self.fixed_size = fixed_size
        self.optional = optional
        self.specific_effects = specific_effects
        self.effects_in_segments = effects_in_segments
        self.minimum_size = minimum_size
        self.maximum_size = maximum_size

        super().__init__(**kwargs)

    def __repr__(self):
        return f"<{self.__class__.__name__}>: {self.__dict__}"

    def __str__(self):
        details = [
            f"fix_effects={self.fi}" if self.fix_effects else ""
            f"divest_effects={self.divest_effects}" if self.divest_effects else ""
            f"specific_effects={self.specific_effects}" if self.specific_effects else ""
            f"Fixed Size" if self.fixed_size else ""
            f"Optional" if self.optional else ""
            f"min/max_Size=[{self.minimum_size}-{self.maximum_size}]"
            f"effects_in_segments={self.effects_in_segments}, " if self.effects_in_segments else ""
        ]

        all_relevant_parts = [part for part in details if part != ""]

        full_str =f"{', '.join(all_relevant_parts)}"

        return f"<{self.__class__.__name__}>: {full_str}"
