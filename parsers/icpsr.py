"""
ICPSR Parser for ingestion into normalized-for-discovery (nfd) metadata store.
"""
import re
import collections
import warnings
import calendar
import json

from datetime import datetime
import dateutil.parser as dup
import xmltodict as x2d

import geocoder

from app.models import NormalizedMetadata


DDI_DOC_URL = 'http://www.ddialliance.org/Specification/DDI-Codebook/2.5/XMLSchema/field_level_documentation.html'


def make_normalized_icpsr(icpsr_file=None):

        raw = RawICPSR(icpsr_file)
        date_range = NormalizedDateEntry(raw)
        geo_center = _extract_geo_center(raw)
        start_date = date_range.start_time
        end_date = date_range.end_time

        title = _extract_title(raw)
        abstract = _extract_abstract(raw)
        identifier = _extract_identifier(raw)

        doc = dict(
            raw=raw.text,
            title=title,
            abstract=abstract,
            identifier=identifier,
            geo_center=geo_center,
            start_datetime=start_date.isoformat(),
            end_datetime=end_date.isoformat(),
            metadata_standard=[{
                'name': 'DDI', 'reference': DDI_DOC_URL
                }]
            )

        # the normalized context is common among all records, by definition
        document_str = json.dumps(doc=normalized,
                                  native_context=DDI_NORMALIZED_FIELDS
        )

        return NormalizedMetadata.from_json(document_str)


DDI_NORMALIZED_CONTEXT = Context.from_json(
    {
        'title': DDI_SPEC_BASE + 'titl',
        'start_datetime': DDI_SPEC_BASE + 'timePrd-start',
        'end_datetime': DDI_SPEC_BASE + 'timePrd-start',
        'native_identifier': DDI_SPEC_BASE + 'IDNo',
        'abstract': DDI_SPEC_BASE + 'abstract'
    }
)


DDI_SPEC_BASE = \
    'http://www.ddialliance.org/Specification/DDI-Codebook/2.5/XMLSchema/'\
    'field_level_documentation_files/schemas/codebook_xsd/elements/'

def _extract_title(raw_icpsr):
    md = raw_icpsr.metadata_dict
    return md['codeBook']['docDscr']['citation']['titlStmt']['titl']


def _extract_identifier(raw_icpsr):
    md = raw_icpsr.metadata_dict
    return md['codeBook']['docDscr']['citation']['titlStmt']['IDNo']


def _extract_abstract(raw_icpsr):
    md = raw_icpsr.metadata_dict
    try:
        abstract = md['codeBook']['stdyDscr']['stdyInfo']['abstract']
        if type(abstract) == list:
            try:
                abstract = "\n".join(abstract)
            except:
                abstract = None

        elif type(abstract) == collections.OrderedDict:
            try:
                abstract = '\n'.join(abstract['p'])
            except:
                try:
                    abstract = abstract['p']
                except:
                    abstract = None

        else:
            abstract = None

        return abstract

    except KeyError:
        return None

def _extract_geo_center(raw_icpsr):

    md = raw_icpsr.metadata_dict
    geo_center = None
    try:
        geo_cover = md['codeBook']['stdyDscr']['stdyInfo']['sumDscr']['geogCover']

        # keeping anti-information out of the system
        if geo_cover == 'United States':
            geo_cover = None

    except:
        geo_cover = None

    if geo_cover and type(geo_cover) == str:

        geoc = geocoder.google(geo_cover)
        s = geoc.south
        w = geoc.west
        n = geoc.north
        e = geoc.east

        lon = w + ((e - w)/2.0)
        lat = s + ((n - s)/2.0)
        geo_center = (lon, lat)

    else:
        # import ipdb; ipdb.set_trace()
        pass

    return geo_center


class NormalizedDateEntry:

    def __init__(self, raw_icpsr):
        self.start_time, self.end_time = _get_time_periods(raw_icpsr)
        self.valid = self.start_time <= self.end_time
        if not self.valid:
            warnings.warn("Start time is greater than end time")


class RawICPSR:

    def __init__(self, icpsr_file=None):
        if icpsr_file:
            self.text = open(icpsr_file).read()
            self.metadata_dict = x2d.parse(self.text)

        else:
            self.text = None
            self.dict = None


def _get_time_periods(raw_icpsr):
    """
    Extracts the time periods to transform

    <timePrd event="start" date="1862" cycle="P1">
    </timePrd>
    <timePrd event="end"   date="1865" cycle="P1">
    </timePrd>

    to a list of dates to be used to build a NormalizedDateEntry.
    """
    md_dict = raw_icpsr.metadata_dict

    # a list
    try:
        time_prds = \
            md_dict['codeBook']['stdyDscr']['stdyInfo']['sumDscr']['timePrd']
    except:
        start_time = datetime(1000, 1, 1)
        end_time = datetime(3000, 1, 1)
        return start_time, end_time

    # on brief inspection these seem to be the dominant date patterns in
    # ICPSR DDI metadata. Unfortunately the standard provides no date format
    # requirements, only suggest ISO 8601
    year_pattern = re.compile('^[0-9]{4}$')
    year_mo_pattern = re.compile('^[0-9]{4}-[0-9][1-2]$')

    if not type(time_prds) is list:

        time_prd = time_prds

        assert time_prd['@event'] == 'single', \
            "Bad Metadata: A single time step must have event type single"

        single_time_period = time_prd['@date']

        if year_pattern.match(single_time_period.strip()):
            year = int(single_time_period)
            start_time = datetime(year, 1, 1)
            end_time = datetime(year, 12, 31)

        elif year_mo_pattern.match(single_time_period.strip()):
            year, mo = (int(el) for el in single_time_period.split('-'))
            start_time = datetime(year, mo, 1)
            end_time = datetime(year, mo, calendar.monthrange(year, mo)[1])

        else:
            try:
                start_time = dup.parse(single_time_period)
                end_time = dup.parse(single_time_period)
            except:
                start_time = datetime(1000, 1, 1)
                end_time = datetime(3000, 12, 31)

    elif len(time_prds) == 2:

        try:
            start_time_period = filter(lambda p: p['@event'] == 'start',
                                       time_prds).pop()['@date']

            end_time_period = filter(lambda p: p['@event'] == 'end',
                                     time_prds).pop()['@date']
        except:
            start_time_period = '1000-01-01'
            end_time_period = '3000-12-31'

        if (year_pattern.match(start_time_period) and
                year_pattern.match(end_time_period)):

            start_time = datetime(int(start_time_period.strip()), 1, 1)
            end_time = datetime(int(end_time_period.strip()), 12, 31)

        elif (year_mo_pattern.match(start_time_period) and
              year_mo_pattern.match(end_time_period)):

            year, mo = (int(el) for el in start_time_period.split('-'))
            # start at beginning of month, day not given
            start_time = datetime(year, mo, 1)
            # end at the end of the month given
            end_time = datetime(year, mo, calendar.monthrange(year, mo)[1])

        else:  # if things are weird, just try dateutil.parse.parse
            start_time = dup.parse(start_time_period)
            end_time = dup.parse(end_time_period)

    else:

        start_time = datetime(1000, 1, 1)
        end_time = datetime(3000, 1, 1)

    return start_time, end_time
}
