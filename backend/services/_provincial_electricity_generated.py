"""
Auto-generated provincial-level annual electricity supply / disposition,
in MWh. Source: Statistics Canada Table 25-10-0021 ("Electric power,
electric utilities and industry, annual supply and disposition"), downloaded
as the published English CSV.

Values are the *latest* reporting year present in the source for each
province. The dict maps province two-letter code → {year, components_mwh}
where `components_mwh` keys are:
  - residential_mwh       (Residential sales of electricity)
  - industrial_mwh        (Mining and manufacturing sales of electricity)
  - other_industry_mwh    (Other industries sales of electricity)
  - agriculture_mwh       (Agriculture sales of electricity)
  - total_sales_mwh       (Total sales to ultimate customers)
  - total_generation_mwh  (Total generation of electricity)

DO NOT EDIT BY HAND - re-run `python -m
backend.scripts.ingest_provincial_electricity`.

Used by:
  - feeder_topology.py CITY_PROFILES (residential MWh anchors winter peak
    estimates for non-Ontario provinces, where OEB Yearbook overlay does
    not apply)
"""

PROVINCIAL_ELECTRICITY_BY_PROVINCE: dict[str, dict] = {
    "AB": {
        "year": 2024,
        "components_mwh": {
            "agriculture_mwh": 203882,
            "industrial_mwh": 2136888,
            "other_industry_mwh": 1375666,
            "residential_mwh": 1279436,
            "total_generation_mwh": 90221168,
            "total_sales_mwh": 4995872,
        },
    },
    "BC": {
        "year": 2024,
        "components_mwh": {
            "agriculture_mwh": 96384,
            "industrial_mwh": 1201506,
            "other_industry_mwh": 1624026,
            "residential_mwh": 2516204,
            "total_generation_mwh": 59485116,
            "total_sales_mwh": 5438120,
        },
    },
    "MB": {
        "year": 2024,
        "components_mwh": {
            "agriculture_mwh": 80742,
            "industrial_mwh": 272699,
            "other_industry_mwh": 628397,
            "residential_mwh": 750965,
            "total_generation_mwh": 30547204,
            "total_sales_mwh": 1732803,
        },
    },
    "NB": {
        "year": 2024,
        "components_mwh": {
            "agriculture_mwh": 10010,
            "industrial_mwh": 455169,
            "other_industry_mwh": 461106,
            "residential_mwh": 833399,
            "total_generation_mwh": 11832535,
            "total_sales_mwh": 1759684,
        },
    },
    "NL": {
        "year": 2024,
        "components_mwh": {
            "agriculture_mwh": 4662,
            "industrial_mwh": 78709,
            "other_industry_mwh": 323127,
            "residential_mwh": 583493,
            "total_generation_mwh": 42666332,
            "total_sales_mwh": 989992,
        },
    },
    "NS": {
        "year": 2024,
        "components_mwh": {
            "agriculture_mwh": 13254,
            "industrial_mwh": 215272,
            "other_industry_mwh": 537915,
            "residential_mwh": 900072,
            "total_generation_mwh": 9454034,
            "total_sales_mwh": 1666512,
        },
    },
    "NT": {
        "year": 2024,
        "components_mwh": {
            "industrial_mwh": 1102,
            "other_industry_mwh": 73763,
            "residential_mwh": 50257,
            "total_generation_mwh": 676294,
            "total_sales_mwh": 125121,
        },
    },
    "NU": {
        "year": 2024,
        "components_mwh": {
            "other_industry_mwh": 72145,
            "residential_mwh": 59985,
            "total_generation_mwh": 201858,
            "total_sales_mwh": 132130,
        },
    },
    "ON": {
        "year": 2024,
        "components_mwh": {
            "agriculture_mwh": 301438,
            "industrial_mwh": 2129783,
            "other_industry_mwh": 6776169,
            "residential_mwh": 6905838,
            "total_generation_mwh": 165403927,
            "total_sales_mwh": 16113228,
        },
    },
    "PE": {
        "year": 2024,
        "components_mwh": {
            "agriculture_mwh": 93513,
            "industrial_mwh": 1850,
            "other_industry_mwh": 124362,
            "residential_mwh": 63321,
            "total_generation_mwh": 611480,
            "total_sales_mwh": 283046,
        },
    },
    "QC": {
        "year": 2024,
        "components_mwh": {
            "agriculture_mwh": 186578,
            "industrial_mwh": 2854766,
            "other_industry_mwh": 5061072,
            "residential_mwh": 6267489,
            "total_generation_mwh": 185864050,
            "total_sales_mwh": 14369905,
        },
    },
    "SK": {
        "year": 2024,
        "components_mwh": {
            "agriculture_mwh": 198931,
            "industrial_mwh": 930851,
            "other_industry_mwh": 1116238,
            "residential_mwh": 774002,
            "total_generation_mwh": 24624583,
            "total_sales_mwh": 3020021,
        },
    },
    "YT": {
        "year": 2024,
        "components_mwh": {
            "industrial_mwh": 4540,
            "other_industry_mwh": 35801,
            "residential_mwh": 30470,
            "total_generation_mwh": 561738,
            "total_sales_mwh": 70810,
        },
    },
}
