#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Usage:  eg.py

"""

import re
import os
import json
import yaml
import datetime
import copy
import gzip
import logging
import logging.config

import tools.utils.utils as utils
from bel_lang.Config import config

# Globals
namespace_key = 'eg'
namespace_def = utils.get_namespace(namespace_key)
ns_prefix = namespace_def['namespace']

# ftp://ftp.ncbi.nih.gov/gene/DATA/gene_history.gz
# ftp://ftp.ncbi.nih.gov/gene/DATA/GENE_INFO/Mammalia/
# ftp://ftp.ncbi.nih.gov/gene/DATA/GENE_INFO/All_Data.gene_info.gz

server = "ftp.ncbi.nlm.nih.gov"
source_data_fp = '/gene/DATA/GENE_INFO/All_Data.gene_info.gz'
source_data_history_fp = '/gene/DATA/gene_history.gz'

# Local data filepath setup
basename = os.path.basename(source_data_fp)
gzip_flag = False
if not re.search('.gz$', basename):  # we basically gzip everything retrieved that isn't already gzipped
    gzip_flag = True
    basename = f'{basename}.gz'
local_data_fp = f'{config["bel_resources"]["file_locations"]["downloads"]}/{namespace_key}_{basename}'

basename = os.path.basename(source_data_history_fp)
gzip_flag = False
if not re.search('.gz$', basename):  # we basically gzip everything retrieved that isn't already gzipped
    gzip_flag = True
    basename = f'{basename}.gz'
local_data_history_fp = f'{config["bel_resources"]["file_locations"]["downloads"]}/{namespace_key}_{basename}'


def get_metadata():
    # Setup metadata info - mostly captured from namespace definition file which
    # can be overridden in belbio_conf.yml file
    dt = datetime.datetime.now().replace(microsecond=0).isoformat()
    metadata = {
        "name": namespace_def['namespace'],
        "namespace": namespace_def['namespace'],
        "description": namespace_def['description'],
        "version": dt,
        "src_url": namespace_def['src_url'],
        "url_template": namespace_def['template_url'],
    }

    return metadata


def update_data_files() -> bool:
    """ Download data files if needed

    Args:
        None
    Returns:
        bool: files updated = True, False if not
    """

    update_cycle_days = config['bel_resources']['update_cycle_days']

    result = utils.get_ftp_file(server, source_data_history_fp, local_data_history_fp, gzip_flag=gzip_flag, days_old=update_cycle_days)
    result = utils.get_ftp_file(server, source_data_fp, local_data_fp, gzip_flag=gzip_flag, days_old=update_cycle_days)

    changed = False
    if 'Downloaded' in result[1]:
        changed = True

    return changed


def get_history():
    """Get history of gene records

    Returns:
        Mapping[str, Mapping[str, int]]: history dict of dicts - new gene_id and old_gene_id
    """

    history = {}
    with gzip.open(local_data_history_fp, 'rt') as fi:

        fi.__next__()  # skip header line

        for line in fi:
            cols = line.split('\t')

            (gene_id, old_gene_id,) = (cols[1], cols[2],)
            if gene_id != '-':
                if history.get(gene_id, None):
                    history[gene_id] = {old_gene_id: 1}

    return history


def build_json(force: bool = False):
    """Build EG namespace json load file

    Args:
        force (bool): build json result regardless of file mod dates

    Returns:
        None
    """

    # Terminology JSONL output filename
    terms_data = config["bel_resources"]["file_locations"]["terms_data"]
    terms_fp = f'{terms_data}/{namespace_key}.jsonl.gz'

    # Don't rebuild file if it's newer than downloaded source file
    if not force:
        if utils.file_newer(terms_fp, local_data_fp):
            log.warning('Will not rebuild data file as it is newer than downloaded source file')
            return False

    terms_data = config["bel_resources"]["file_locations"]["terms_data"]
    species_labels_fn = f'{terms_data}/tax_labels.json.gz'
    with gzip.open(species_labels_fn, 'r') as fi:
        species_label = json.load(fi)

    missing_entity_types = {}
    bel_entity_type_map = {
        'snoRNA': ['Gene', 'RNA'],
        'snRNA': ['Gene', 'RNA'],
        'ncRNA': ['Gene', 'RNA'],
        'tRNA': ['Gene', 'RNA'],
        'scRNA': ['Gene', 'RNA'],
        'other': ['Gene'],
        'pseudo': ['Gene', 'RNA'],
        'unknown': ['Gene', 'RNA', 'Protein'],
        'protein-coding': ['Gene', 'RNA', 'Protein'],
        'rRNA': ['Gene', 'RNA'],
    }

    history = get_history()

    with gzip.open(local_data_fp, 'rt') as fi, gzip.open(terms_fp, 'wt') as fo:

        # Header JSONL record for terminology
        metadata = get_metadata()
        fo.write("{}\n".format(json.dumps({'metadata': metadata})))

        fi.__next__()  # skip header line

        for line in fi:

            cols = line.split('\t')
            (tax_src_id, gene_id, symbol, synonyms, desc, gene_type, name) = (cols[0], cols[1], cols[2], cols[4], cols[8], cols[9], cols[11], )
            tax_id = f'TAX:{tax_src_id}'

            synonyms = synonyms.rstrip()
            if synonyms == '-':
                synonyms = None
            else:
                synonyms = synonyms.split('|')

            if gene_type in ['miscRNA', 'biological-region']:  # Skip gene types
                continue
            elif gene_type not in bel_entity_type_map:
                log.error(f'Unknown gene_type found {gene_type}')
                missing_entity_types[gene_type] = 1
                entity_types = None
            else:
                entity_types = bel_entity_type_map[gene_type]

            if name == '-':
                name = symbol

            term = {
                'namespace': ns_prefix,
                'src_id': gene_id,
                'id': utils.get_prefixed_id(ns_prefix, gene_id),
                'label': symbol,
                'name': name,
                'description': desc,
                'species_id': tax_id,
                'species_label': species_label.get(tax_id, None),
            }
            if name != '-':
                term['name'] = name

            if synonyms:
                term['synonyms'] = copy.copy(synonyms)

            if entity_types:
                term['entity_types'] = copy.copy(entity_types)

            if gene_id in history:
                term['obsolete_ids'] = history[gene_id].keys()

            # Add term to JSONL
            fo.write("{}\n".format(json.dumps({'term': term})))

    if missing_entity_types:
        log.error('Missing Entity Types:\n', json.dumps(missing_entity_types))


def main():

    update_data_files()
    build_json()


if __name__ == '__main__':
    # Setup logging
    module_fn = os.path.basename(__file__)
    module_fn = module_fn.replace('.py', '')

    logging_conf_fn = config['bel_resources']['file_locations']['logging_conf_fn']
    with open(logging_conf_fn, mode='r') as f:
        logging.config.dictConfig(yaml.load(f))
        log = logging.getLogger(f'{module_fn}-terms')

    main()
