"""
This script shows how load results of a prior calcualtion and how to analyze them.
"""

import pandas as pd
import plotly.offline
import flixOpt as fx

if __name__ == '__main__':
    # --- Load Results ---
    try:
        results = fx.results.CalculationResults('Sim1', folder='results')
    except FileNotFoundError:
        raise FileNotFoundError('Results file was not found. DId you run complex_example.py already?')

    # --- Basic overview ---
    results.visualize_network()
    results.plot_operation('Fernwärme')
    results.plot_operation('Fernwärme', 'bar')
    results.plot_operation('Fernwärme', 'bar', engine='matplotlib')

    # --- Detailed Plots ---
    # In depth plot for individual flow rates ('__' is used as the delimiter between Component and Flow
    results.plot_operation('Wärmelast__Q_th_Last', 'heatmap')
    figs = []
    for flow_label in results.flow_results():
        if flow_label.startswith('BHKW2'):
            fig = results.plot_operation(flow_label, 'heatmap', heatmap_steps_per_period='h', heatmap_periods='D')


    # --- Plotting internal variables manually ---
    on_data = pd.DataFrame({'BHKW2 On': results.component_results['BHKW2'].variables['Q_th']['OnOff']['on'],
                           'Kessel On': results.component_results['Kessel'].variables['Q_th']['OnOff']['on']},
                           index = results.time)
    fig = fx.plotting.with_plotly(on_data, 'line')
    fig.write_html('results/on.html')  # Writing to file

    fig = fx.plotting.with_plotly(on_data, 'bar')
    fig.update_layout(barmode='group', bargap=0.1) # Applying custom layout
    plotly.offline.plot(fig)