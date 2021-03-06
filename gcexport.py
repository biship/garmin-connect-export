#!/usr/bin/python
# -*- coding: utf-8

from __future__ import unicode_literals

from datetime import datetime
from getpass import getpass
import sys
import os
from xml.dom.minidom import parseString
import requests
import argparse
import zipfile
import logging
import json
from urllib.parse import urlencode
from importlib import reload


def parse_args():

    # TODO: duplicate
    CURRENT_DATE = datetime.now().strftime('%Y-%m-%d')

    DEFAULT_DIRECTORY = './' + CURRENT_DATE + '_garmin_connect_export'

    parser = argparse.ArgumentParser()

    parser.add_argument('--username',
                        help=('your Garmin Connect username '
                              '(otherwise, you will be prompted)'),
                        nargs='?')

    parser.add_argument('--password',
                        help=('your Garmin Connect password '
                              '(otherwise, you will be prompted)'),
                        nargs='?')

    parser.add_argument('-c', '--count', nargs='?', default='1',
                        help=('number of recent activities to download,'
                              " or 'all' (default: 1)"))


    parser.add_argument('-f', '--format', nargs='?', default='gpx',
                        choices=['gpx', 'tcx', 'original', 'json'],
                        help=("export format; can be 'gpx', 'tcx',"
                              " 'original', or 'json' (default: 'gpx')"))

    parser.add_argument('-d', '--directory', nargs='?',
                        default=DEFAULT_DIRECTORY,
                        help=('the directory to export to (default:'
                              " './YYYY-MM-DD_garmin_connect_export')"))

    parser.add_argument('-u', '--unzip',
                        help=("if downloading ZIP files (format: 'original'),"
                              ' unzip the file and removes the ZIP file'),
                        action='store_true')

    return parser.parse_args()


def logged_in_session(username, password, data):

    # TODO: duplicate
    GCU = 'https://connect.garmin.com/'

    url_gc_login = 'https://sso.garmin.com/sso/login?' + urlencode(data)
    url_gc_post_auth = GCU + 'post-auth/login?'

    # Create a session that will persist thorughout this script
    sesh = requests.Session()

    sesh.headers['User-Agent'] = ('Mozilla/5.0 (X11; Linux x86_64) '
                                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                                  'Chrome/29.0.1547.62 Safari/537.36')

    # Initially, we need to get a valid session cookie,
    # so we pull the login page.
    r1 = sesh.get(url_gc_login)

    # Now we'll actually login, using
    # fields that are passed in a typical Garmin login.
    post_data = {'username': username,
                 'password': password,
                 'embed': 'true',
                 'lt': 'e1s1',
                 '_eventId': 'submit',
                 'displayNameRequired': 'false'}

    r2 = sesh.post(url_gc_login, data=post_data)

    if 'CASTGC' in r2.cookies:
        # Construct login ticket from the  cookie with 'CASTCG' key
        login_ticket = 'ST-0' + r2.cookies['CASTGC'][4:]

    else:
        raise Exception('Did not get a ticket cookie. Cannot log in.'
            ' Did you enter the correct username and password?')

    r3 = sesh.post(url_gc_post_auth, params={'ticket': login_ticket})

    return sesh


def gcexport(args=None):

    if args is None:
        args = parse_args()

    # TODO: duplicate
    CURRENT_DATE = datetime.now().strftime('%Y-%m-%d')

    # URLs for various services.
    GCU = 'https://connect.garmin.com/'
    REDIRECT = GCU + 'post-auth/login'
    BASE_URL = GCU + 'en-US/signin'
#    GAUTH = GCU + 'gauth/hostname'
    SSO = 'https://sso.garmin.com/sso'
    CSS = ('https://static.garmincdn.com/com.garmin.connect/ui/css/'
           'gauth-custom-v1.1-min.css')

    data = {'service': REDIRECT,
            'webhost': 'olaxpw-connect04',
            'source': BASE_URL,
            'redirectAfterAccountLoginUrl': REDIRECT,
            'redirectAfterAccountCreationUrl': REDIRECT,
            'gauthHost': SSO,
            'locale': 'en_US',
            'id': 'gauth-widget',
            'cssUrl': CSS,
            'clientId': 'GarminConnect',
            'rememberMeShown': 'true',
            'rememberMeChecked': 'false',
            'createAccountShown': 'true',
            'openCreateAccount': 'false',
            'usernameShown': 'false',
            'displayNameShown': 'false',
            'consumeServiceTicket': 'false',
            'initialFocus': 'true',
            'embedWidget': 'false',
            'generateExtraServiceTicket': 'false'}


    url_gc_search = GCU + 'proxy/activity-search-service-1.2/json/activities?'
    modern_export = 'modern/proxy/download-service/export/'
    url_gc_gpx_activity = GCU + modern_export + 'gpx/activity/'
    url_gc_tcx_activity = GCU + modern_export + 'tcx/activity/'
    url_gc_original_activity = GCU + 'proxy/download-service/files/activity/'

    reload(logging)
    logging.basicConfig(filename='import_{}.log'.format(CURRENT_DATE),
        format='%(levelname)s:%(message)s',
        level=logging.DEBUG)  # use level=logging.INFO for less verbosity


    py2 = sys.version_info[0] < 3  # is this python 2?

    logging.info('Welcome to Garmin Connect Exporter!')

    username = args.username if args.username else input('Username: ')
    password = args.password if args.password else getpass()

    # Create directory for data files.
    if os.path.isdir(args.directory):
        logging.info('Warning: Output directory already exists.'
                     ' Will skip already-downloaded files.')

    # We should be logged in now.
    sesh = logged_in_session(username, password, data)

    logging.info('Call modern')
    sesh.get(GCU + 'modern')
    logging.info('Finish modern')
    logging.info('Call legacy session')
    sesh.get(GCU + 'legacy/session')
    logging.info('Finish legacy session')

    if not os.path.isdir(args.directory):
        os.mkdir(args.directory)

    download_all = False

    if args.count == 'all':
        # If the user wants to download all activities, first download one,
        # then the result of that request will tell us how many are available
        # so we will modify the variables then.
        total_to_download = 1
        download_all = True
    else:
        total_to_download = int(args.count)

    total_downloaded = 0

    # This while loop will download data from the server in multiple chunks,
    # if necessary.

    while total_downloaded < total_to_download:
        # Maximum of 100... 400 return status if over 100.  So download 100 or
        # whatever remains if less than 100.
        if total_to_download - total_downloaded > 100:
            num_to_download = 100
        else:
            num_to_download = total_to_download - total_downloaded

        search_params = {'start': total_downloaded, 'limit': num_to_download}

        # Query Garmin Connect
        # TODO: Catch possible exceptions here.
        json_results = sesh.get(url_gc_search, params=search_params).json()
        #print(json_results['results'].keys())
        #search = json_results['results']['search']

        if download_all:
            # Modify total_to_download based on how many activities the server
            # reports.
            total_to_download = int(json_results['results']['totalFound'])
            # Do it only once.
            download_all = False

        # Pull out just the list of activities.
        activities = json_results['results']['activities']

        # Process each activity.
        for a in activities:
            A = a['activity']
            aSummary = A['activitySummary']

            # Display which entry we're working on.
            info = {
                'id': A['activityId'],
                'name': A['activityName'],
                'timestamp': aSummary['BeginTimestamp']['display'],
                'duration': '??:??:??',
                'distance': '0.00 Miles'
            }

            if 'SumElapsedDuration' in aSummary:
                info['duration'] = aSummary['SumElapsedDuration']['display']

            if 'SumDistance' in A['activitySummary']:
                info['distance'] = aSummary['SumDistance']['withUnit']

            logging.info('Garmin Connect activity: [{id}] {name}\n'
                         '\t{timestamp}, {duration}, {distance}'
                         .format(**info))

            if args.format == 'gpx':
                data_filename = 'activity_{}.gpx'.format(info['id'])
                download_url = ('{}{}?full=true'
                                .format(url_gc_gpx_activity, info['id']))
                file_mode = 'w'

            elif args.format == 'tcx':
                data_filename = 'activity_{}.tcx'.format(info['id'])

                download_url = ('{}{}?full=true'
                                .format(url_gc_tcx_activity, info['id']))
                file_mode = 'w'

            elif args.format == 'json':
                data_filename = 'activity_{}.json'.format(info['id'])
                file_mode = 'w'

            elif args.format == 'original':
                data_filename = 'activity_{}.zip'.format(info['id'])

                fit_filename = info['id'] + '.fit'

                download_url = url_gc_original_activity + info['id']
                file_mode = 'wb'
            else:
                raise Exception('Unrecognized format.')

            # file_path is the full path of the activity file to write
            file_path = args.directory + '/' + data_filename

            # Increase the count now, since we want to count skipped files.
            total_downloaded += 1

            if args.format == 'json':
                with open(file_path, file_mode) as save_file:
                    save_file.write(json.dumps(A, indent=2))
                continue

            if (os.path.isfile(file_path) or
                    # Regardless of unzip setting, don't redownload if the
                    # ZIP or FIT file exists.
                    (args.format == 'original' and
                        os.path.isfile(fit_filename))):
                logging.info('%s already exists; skipping...', data_filename)
                continue

            # Download the data file from Garmin Connect.
            # If the download fails (e.g., due to timeout), this script will
            # die, but nothing will have been written to disk about this
            # activity, so just running it again should pick up where it left
            # off.
            logging.info('Downloading activity...')

            try:
                empty_file = False
                file_response = sesh.get(download_url)

            except requests.HTTPError as e:

                # Handle expected (though unfortunate) error codes; die on
                # unexpected ones.
                if e.code == 500 and args.format == 'tcx':
                    # Garmin will give an internal server error (HTTP 500) when
                    # downloading TCX files if the original was a manual GPX
                    # upload. Writing an empty file prevents this file from
                    # being redownloaded, similar to the way GPX files are
                    # saved even when there are no tracks. One could be
                    # generated here, but that's a bit much. Use the GPX format
                    # if you want actual data in every file, as I believe
                    # Garmin provides a GPX file for every activity.
                    logging.info('Writing empty file since Garmin did not'
                                 ' generate a TCX file for this activity...')
                    empty_file = True

                elif e.code == 404 and args.format == 'original':
                    # For manual activities (i.e., entered in online without a
                    # file upload), there is no original file.
                    # Write an empty file to prevent redownloading it.
                    logging.info('Writing empty file since there'
                                 ' was no original activity data...')
                    empty_file = True
                else:
                    raise Exception(
                        'Failed. Got an unexpected HTTP error ({}).'
                        .format(str(e.code))
                    )

            if empty_file:
                data = ''
            elif 'b' in file_mode:
                # if response contains binary data, i.e. file_mode is 'wb'
                data = file_response.content
            else:
                # otherwise, data is (auto-detected, most likely utf8)
                # encoded text
                data = file_response.text
                if py2:
                    # in python 2 we need to explicitly encode the unicode
                    #  into something that can be written to a file.
                    # If we don't do this then the write will fail for
                    #  many non-english characters.
                    data = data.encode(file_response.encoding)

            with open(file_path, file_mode) as save_file:
                save_file.write(data)

            if args.format == 'gpx':
                # Validate GPX data. If we have an activity without GPS data
                # (e.g., running on a treadmill), Garmin Connect still kicks
                # out a GPX, but there is only activity information,
                # no GPS data. N.B. You can omit the XML parse
                # (and the associated log messages) to speed things up.
                try:
                    # Sometimes trying to parse the gpx file or find a trkpt
                    #  tag raises an exception.
                    # We handle this here so it won't
                    #  stop the script.
                    gpx = parseString(data)
                    gpx_data_exists = len(gpx.getElementsByTagName('trkpt'))>0
                except:
                    gpx_data_exists = False

                if gpx_data_exists:
                    logging.info('Done. GPX data saved.')
                else:
                    logging.info('Done. No track points found.')

            elif args.format == 'original':
                # Even manual upload of a GPX file is zipped, but we'll
                # validate the extension.
                if (args.unzip and
                        file_path[-3:].lower() == 'zip' and
                        os.stat(file_path).st_size > 0):
                    logging.info('Unzipping and removing original files...')
                    zip_file = open(file_path, 'rb')
                    z = zipfile.ZipFile(zip_file)
                    for name in z.namelist():
                        z.extract(name, args.directory)

                    zip_file.close()
                    os.remove(file_path)

        # End while loop for multiple chunks.
        logging.info('Chunk done!')
    logging.info('Done!')


if __name__ == '__main__':

    gcexport()
