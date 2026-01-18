from dash import Dash, dcc, html
import plotly.express as px
import pandas as pd
import numpy as np

x = np.linspace(0, 10, 100)
df = pd.DataFrame({"x": x, "y": np.sin(x)})

fig = px.line(df, x="x", y="y")

app = Dash(__name__)
app.layout = html.Div([
    html.H1("Dash Plot"),
    dcc.Graph(figure=fig)
])

if __name__ == "__main__":
    app.run(debug=True)
