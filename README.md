# Hawker Centre Inspection Planning

This repository contains the code and data for our DBA5103 group project.

## Repository outline

```text
.
├── data/
│   ├── raw/                 # Source hawker-centre and electoral-boundary data
│   └── processed/           # Processed nodes, travel matrices, and map
├── src/
│   └── process_data.py      # Prepares the project data
├── requirements.txt         # Python dependencies
└── README.md
```

## Setup

1. Install Python 3.10 or later.
2. From the repository folder, create the virtual environment.

```bash
python -m venv venv
```

3. Activate the virtual environment.

Windows (PowerShell):

```powershell
.\venv\Scripts\activate
```

macOS/Linux:

```bash
source venv/bin/activate
```

4. Install the dependencies needed:

```bash
pip install -r requirements.txt
```

## Run the data-processing code

The processed files are already included in `data/processed/`. You only need to run this step again if you want to regenerate them from the raw data.

From the repository folder, run:

```bash
python src/process_data.py
```

The script reads the GeoJSON files in `data/raw/`, selects eligible hawker centres in the West Coast–Jurong West GRC, adds the depot, and requests road travel-time and distance estimates from OSRM. It then saves the results in `data/processed/`. Running it again replaces the existing generated files.

An internet connection is required for the OSRM routing request.

## Processed data for modelling

The processing code creates the following files:

- `data/processed/nodes.csv` - the depot and selected hawker centres, with their node IDs, details, and coordinates. Node 0 is the depot.
- `data/processed/time_matrix_min.csv` - estimated driving time in minutes between each pair of nodes.
- `data/processed/distance_matrix_km.csv` - estimated driving distance in kilometres between each pair of nodes.
- `data/processed/map.png` - a map showing the depot and selected hawker centres.

## Notes

The travel matrices contain OSRM driving estimates and do not account for live traffic. Travel estimates may change if OSRM's routing data is updated.
