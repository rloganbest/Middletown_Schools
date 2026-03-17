"""
TGES domain models — County and District enums for type-safe filtering.

Usage:
    county_filter = [County.MONMOUTH.value]   # ["Monmouth"]
    primary = District.MIDDLETOWN.display_name
    df[df["county"] == District.MIDDLETOWN.county.value]
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class County(Enum):
    """NJ county names (as they appear in TGES data)."""

    MONMOUTH = "Monmouth"
    OCEAN = "Ocean"
    MERCER = "Mercer"
    MIDDLESEX = "Middlesex"
    BERGEN = "Bergen"
    ESSEX = "Essex"
    HUDSON = "Hudson"
    UNION = "Union"
    SOMERSET = "Somerset"
    MORRIS = "Morris"
    BURLINGTON = "Burlington"
    CAMDEN = "Camden"
    GLOUCESTER = "Gloucester"
    ATLANTIC = "Atlantic"
    CAPE_MAY = "Cape May"
    CUMBERLAND = "Cumberland"
    SALEM = "Salem"
    WARREN = "Warren"
    SUSSEX = "Sussex"
    HUNTERDON = "Hunterdon"
    PASSAIC = "Passaic"
    MORRIS_ESS = "Morris-Essex"  # Regional if present


@dataclass(frozen=True)
class DistrictInfo:
    """District metadata: name as in TGES, state code, and county."""

    name: str
    district_code: str
    county: County


class District(Enum):
    """Known districts with metadata. Use .name, .district_code, .county."""

    MIDDLETOWN = DistrictInfo("Middletown Twp", "3160", County.MONMOUTH)
    RUMSON_BORO = DistrictInfo("Rumson Boro", "3165", County.MONMOUTH)
    RUMSON_FAIR_HAVEN = DistrictInfo("Rumson-Fair Haven Reg", "3170", County.MONMOUTH)

    @property
    def display_name(self) -> str:
        """Name as it appears in TGES CSV (DISTNAME)."""
        return self.value.name

    @property
    def district_code(self) -> str:
        """State-assigned district code (DIST)."""
        return self.value.district_code

    @property
    def county(self) -> County:
        """County this district belongs to."""
        return self.value.county
