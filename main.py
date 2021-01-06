import csv
from io import BytesIO
import json
from typing import Any
import xmltodict
import httpx
from zipfile import ZipFile

ELECTION_ID = "107556"


def get_current_version(election_id: str) -> str:
    return httpx.get(
        f"https://results.enr.clarityelections.com/GA/{election_id}/current_ver.txt"
    ).text


def get_election_settings(election_id: str, current_version: str):
    response = httpx.get(
        f"https://results.enr.clarityelections.com/GA/{election_id}/{current_version}/json/en/electionsettings.json"
    )

    return response.json()


def get_participating_counties(election_id: str, current_version: str):
    election_settings = get_election_settings(election_id, current_version)

    strings = election_settings["settings"]["electiondetails"]["participatingcounties"]

    participating_counties = []

    for string in strings:
        parts = string.split("|")

        county = parts[0]
        county_election_id = parts[1]
        county_current_version = parts[2]

        participating_counties.append(
            {
                "county": county,
                "election_id": county_election_id,
                "current_version": county_current_version,
                "xml_url": f"https://results.enr.clarityelections.com/GA/{county}/{county_election_id}/{county_current_version}/reports/detailxml.zip",
            }
        )

    return participating_counties


def get_xml(url: str):
    response = httpx.get(url)

    if response.status_code != 200:
        return None

    zipfile = ZipFile(BytesIO(response.read()))

    xml = zipfile.read("detail.xml")

    return xml


def postprocessor(_: str, key: str, value: Any):
    if key in (
        "ballotsCast",
        "countiesParticipating",
        "countiesReported",
        "precinctsParticipating",
        "precinctsReported",
        "precinctsReporting",
        "totalVoters",
        "totalVotes",
        "voteFor",
        "votes",
    ):
        return key, int(value)
    elif key in (
        "precinctsReportingPercent",
        "voterTurnout",
    ):
        return key, float(value)
    else:
        return key, value


def convert_xml_to_dict(xml: str):
    return xmltodict.parse(
        xml,
        attr_prefix="",
        force_list=(
            "County",
            "Precinct",
        ),
        postprocessor=postprocessor,
    )


PERDUE_RACE_ID = "2"
PERDUE_ID = "4"
OSSOFF_ID = "5"

LOEFFLER_RACE_ID = "3"
LOEFFLER_ID = "19"
WARNOCK_ID = "25"


def main():
    current_version = get_current_version(ELECTION_ID)
    counties = get_participating_counties(ELECTION_ID, current_version)

    with open("matches.csv") as infile:
        matches = csv.DictReader(infile)
        matches = dict(((row["name"], row["county"]), row["sosid"]) for row in matches)

    # georgia = {
    #     "county": "Georgia",
    #     "election_id": ELECTION_ID,
    #     "current_version": current_version,
    #     "xml_url": f"https://results.enr.clarityelections.com/GA/{ELECTION_ID}/{current_version}/reports/detailxml.zip",
    # }

    all_precincts = []

    for county in counties:
        xml = get_xml(county["xml_url"])

        if not xml:
            continue

        obj = convert_xml_to_dict(xml)
        xml_county = obj["ElectionResult"]["Region"]

        with open(f"raw/{county['county'].lower()}.json", "w") as outfile:
            outfile.write(json.dumps(obj, indent=2))

        precincts = dict(
            (precinct["name"], precinct)
            for precinct in obj["ElectionResult"]["VoterTurnout"]["Precincts"][
                "Precinct"
            ]
        )

        for p in precincts.values():
            p["perdue"] = 0
            p["ossoff"] = 0
            p["loeffler"] = 0
            p["warnock"] = 0
            p["county"] = xml_county
            p["sosid"] = matches.get((p["name"], xml_county))

        perdue_contest = next(
            c for c in obj["ElectionResult"]["Contest"] if c["key"] == PERDUE_RACE_ID
        )
        choices = perdue_contest["Choice"]

        perdue = next(c for c in choices if c["key"] == PERDUE_ID)

        for vote_type in perdue["VoteType"]:
            for precinct in vote_type["Precinct"]:
                match = precincts.get(precinct["name"])

                match["perdue"] += precinct["votes"]

        ossoff = next(c for c in choices if c["key"] == OSSOFF_ID)

        for vote_type in ossoff["VoteType"]:
            for precinct in vote_type["Precinct"]:
                match = precincts.get(precinct["name"])

                match["ossoff"] += precinct["votes"]

        loeffler_contest = next(
            c for c in obj["ElectionResult"]["Contest"] if c["key"] == LOEFFLER_RACE_ID
        )
        choices = loeffler_contest["Choice"]

        loeffler = next(c for c in choices if c["key"] == LOEFFLER_ID)

        for vote_type in loeffler["VoteType"]:
            for precinct in vote_type["Precinct"]:
                match = precincts.get(precinct["name"])

                match["loeffler"] += precinct["votes"]

        warnock = next(c for c in choices if c["key"] == WARNOCK_ID)

        for vote_type in warnock["VoteType"]:
            for precinct in vote_type["Precinct"]:
                match = precincts.get(precinct["name"])

                match["warnock"] += precinct["votes"]

        all_precincts = all_precincts + list(precincts.values())

    with open(f"precincts.json", "w") as outfile:
        outfile.write(json.dumps(all_precincts, indent=2))

    with open(f"precincts.csv", "w") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=all_precincts[0].keys())
        writer.writeheader()

        writer.writerows(all_precincts)

    print(len(all_precincts))


if __name__ == "__main__":
    main()