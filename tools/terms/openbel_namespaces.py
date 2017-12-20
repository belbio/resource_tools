#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Usage:  program.py <customer>

"""
import sys
import os.path
import gzip
import copy
import json
import yaml
import re

import logging
import logging.config

import tools.utils.utils as utils
from tools.utils.Config import config

entity_type_conversion = {
    'A': 'Abundance',
    'B': 'BiologicalProcess',
    'C': 'Complex',
    'G': 'Gene',
    'M': 'Micro_RNA',
    'O': 'Pathology',
    'P': 'Protein',
    'R': 'RNA',
}


def update_data_files() -> bool:

    nsfiles = []

    for key in config["bel_resources"]["openbel"]["openbel_namespace_sources"]:
        url = config["bel_resources"]["openbel"]["openbel_namespace_sources"][key]

        basename = os.path.basename(url)
        gzip_flag = False
        if not re.search('.gz$', basename):  # we basically gzip everything retrieved that isn't already gzipped
            gzip_flag = True
            basename = f'{basename}.gz'
        local_fn = f'{config["bel_resources"]["file_locations"]["downloads"]}/{basename}'

        nsfiles.append((local_fn, url))
        update_cycle_days = config['bel_resources']['update_cycle_days']
        utils.get_web_file(url, local_fn, gzip_flag=gzip_flag, days_old=update_cycle_days)

    return nsfiles


def convert_entity_types(entity_types_abbrev):

    entity_types = []
    for et in entity_types_abbrev:
        et = et.upper()
        entity_types.append(entity_type_conversion[et])

    return entity_types


def read_nsfile(nsfile):

    ns = {'Values': []}
    with gzip.open(nsfile, 'rt', encoding='utf-8') as fi:

        for line in fi:
            section_match = re.match('^\[(\w+)\]', line)
            keyval_match = re.match('^(\w+?)=(.*)$', line)
            blank_match = re.match('^\s*$', line)
            val_match = re.match('^([\w\_\d].*\|.*)', line)
            if section_match:
                section = section_match.group(1)
                if section != 'Values':
                    ns[section] = {}

            elif keyval_match:
                key = keyval_match.group(1)
                val = keyval_match.group(2)
                if key not in ns[section]:
                    ns[section][key] = []
                ns[section][key].append(val)

            elif blank_match:
                pass

            elif val_match:
                val = val_match.group(1)
                (term_id, entity_types_abbrev) = val.split('|')
                entity_types = convert_entity_types(entity_types_abbrev)

                # ns_match = re.match('^([A-Z]+)_(.*)$', vid)
                # if ns_match:
                #     namespace = ns_match.group(1)
                #     _id = ns_match.group(2)

                ns[section].append({'term_id': f'{term_id}', 'entity_types': entity_types})

    return ns


def build_json(nsfiles):

    for nsfile, nsfile_src_url in nsfiles:
        print('Processing belns', os.path.basename(nsfile))

        ns_dict = read_nsfile(nsfile)

        idx_len = len(ns_dict['Citation']['NameString'])

        for idx in range(idx_len):

            metadata = {}
            namespace = ns_dict['Namespace']['Keyword'][0]
            species_id = ''

            if re.match('\d+$', ns_dict['Namespace']['SpeciesString'][0]):
                species_id = ns_dict['Namespace']['SpeciesString']

            # print('Namespace: ', namespace, ' Species: ', species_id, 'SpeciesString', ns_dict['Namespace']['SpeciesString'][0])

            terms_filename = f'{config["bel_resources"]["file_locations"]["terms_data"]}/{namespace}_belns.jsonl.gz'

            ref_url = ''
            if 'ReferenceURL' in ns_dict['Citation']:
                ref_url = ns_dict['Citation']['ReferenceURL'][idx]

            version = ''
            if 'PublishedVersionString' in ns_dict['Citation']:
                version = ns_dict['Citation']['PublishedVersionString'][idx]

            metadata = {
                'name': ns_dict['Citation']['NameString'][idx],
                'namespace': namespace,
                'description': f"{ns_dict['Namespace']['DescriptionString'][idx]}. NOTE: Converted from OpenBEL belns file {nsfile_src_url}",
                'src_url': ref_url,
                'version': version,
            }

            terms = []
            for value in ns_dict['Values']:

                name = value['term_id']
                alt_ids = []

                term_id = utils.get_prefixed_id(namespace, name)

                entity_types = value['entity_types']
                term = {
                    "namespace": namespace,
                    "id": term_id,
                    "name": name,
                    "entity_types": entity_types,
                }
                if alt_ids:
                    term['alt_ids'] = alt_ids

                if namespace == 'ZFIN':
                    term['species_id'] = 'TAX:7955'
                    term['species_label'] = 'zebrafish'
                terms.append(copy.deepcopy(term))

            with gzip.open(terms_filename, 'wt') as fo:
                fo.write("{}\n".format(json.dumps({'metadata': metadata})))

                for term in terms:
                    fo.write("{}\n".format(json.dumps({'term': term})))


def main():

    nsfiles = update_data_files()
    build_json(nsfiles)


if __name__ == '__main__':
    # Setup logging
    global log
    module_fn = os.path.basename(__file__)
    module_fn = module_fn.replace('.py', '')

    logging_conf_fn = f'{config["bel_resources"]["file_locations"]["root"]}/logging_conf.yml'
    with open(logging_conf_fn, mode='r') as f:
        logging.config.dictConfig(yaml.load(f))
        log = logging.getLogger(f'{module_fn}-terms')

    main()