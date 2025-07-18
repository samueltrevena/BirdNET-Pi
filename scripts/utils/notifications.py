import html
import os
import socket
import sqlite3
import time as timeim
from datetime import datetime

import apprise
import requests

userDir = os.path.expanduser('~')
APPRISE_CONFIG = userDir + '/BirdNET-Pi/apprise.txt'
DB_PATH = userDir + '/BirdNET-Pi/scripts/birds.db'

flickr_images = {}
species_last_notified = {}

asset = apprise.AppriseAsset(
    plugin_paths=[
        userDir + "/.apprise/plugins",
        userDir + "/.config/apprise/plugins",
    ]
)
apobj = apprise.Apprise(asset=asset)
config = apprise.AppriseConfig()
config.add(APPRISE_CONFIG)
apobj.add(config)


def notify(body, title, attached=""):
    if attached != "":
        apobj.notify(
            body=body,
            title=title,
            attach=attached,
        )
    else:
        apobj.notify(
            body=body,
            title=title,
        )


def sendAppriseNotifications(species, confidence, confidencepct, path,
                             date, time, week, latitude, longitude, cutoff,
                             sens, overlap, settings_dict, db_path=DB_PATH):
    def render_template(template, reason=""):
        ret = template.replace("$sciname", sciName) \
            .replace("$comname", comName) \
            .replace("$confidencepct", confidencepct) \
            .replace("$confidence", confidence) \
            .replace("$listenurl", listenurl) \
            .replace("$friendlyurl", friendlyurl) \
            .replace("$date", date) \
            .replace("$time", time) \
            .replace("$week", week) \
            .replace("$latitude", latitude) \
            .replace("$longitude", longitude) \
            .replace("$cutoff", cutoff) \
            .replace("$sens", sens) \
            .replace("$flickrimage", image_url if "{" in body else "") \
            .replace("$overlap", overlap) \
            .replace("$reason", reason)
        return ret
    # print(sendAppriseNotifications)
    # print(settings_dict)
    if os.path.exists(APPRISE_CONFIG) and os.path.getsize(APPRISE_CONFIG) > 0:

        title = html.unescape(settings_dict.get('APPRISE_NOTIFICATION_TITLE'))
        body = html.unescape(settings_dict.get('APPRISE_NOTIFICATION_BODY'))
        sciName, comName = species.split("_")

        APPRISE_ONLY_NOTIFY_SPECIES_NAMES = settings_dict.get('APPRISE_ONLY_NOTIFY_SPECIES_NAMES')
        if APPRISE_ONLY_NOTIFY_SPECIES_NAMES is not None and APPRISE_ONLY_NOTIFY_SPECIES_NAMES.strip() != "":
            if any(bird.lower().replace(" ", "") in comName.lower().replace(" ", "") for bird in APPRISE_ONLY_NOTIFY_SPECIES_NAMES.split(",")):
                return

        APPRISE_ONLY_NOTIFY_SPECIES_NAMES_2 = settings_dict.get('APPRISE_ONLY_NOTIFY_SPECIES_NAMES_2')
        if APPRISE_ONLY_NOTIFY_SPECIES_NAMES_2 is not None and APPRISE_ONLY_NOTIFY_SPECIES_NAMES_2.strip() != "":
            if not any(bird.lower().replace(" ", "") in comName.lower().replace(" ", "") for bird in APPRISE_ONLY_NOTIFY_SPECIES_NAMES_2.split(",")):
                return

        APPRISE_MINIMUM_SECONDS_BETWEEN_NOTIFICATIONS_PER_SPECIES = settings_dict.get('APPRISE_MINIMUM_SECONDS_BETWEEN_NOTIFICATIONS_PER_SPECIES')
        if APPRISE_MINIMUM_SECONDS_BETWEEN_NOTIFICATIONS_PER_SPECIES != "0":
            if species_last_notified.get(comName) is not None:
                try:
                    if int(timeim.time()) - species_last_notified[comName] < int(APPRISE_MINIMUM_SECONDS_BETWEEN_NOTIFICATIONS_PER_SPECIES):
                        return
                except Exception as e:
                    print("APPRISE NOTIFICATION EXCEPTION: "+str(e))
                    return

        # TODO: this all needs to be changed, we changed the caddy default to allow direct IP access, so birdnetpi.local shouldn't be relied on anymore
        try:
            websiteurl = settings_dict.get('BIRDNETPI_URL')
            if len(websiteurl) == 0:
                raise ValueError('Blank URL')
        except Exception:
            websiteurl = "http://"+socket.gethostname()+".local"

        listenurl = websiteurl+"?filename="+path
        friendlyurl = "[Listen here]("+listenurl+")"
        image_url = ""

        if "$flickrimage" in body:
            if comName not in flickr_images:
                try:
                    # Use Wikipedia API instead of Flickr
                    headers = {'User-Agent': 'Python_BirdNET-Pi/1.0'}
                    
                    # Try scientific name first
                    sci_name_url = sciName.replace(' ', '_')
                    url = f'https://en.wikipedia.org/api/rest_v1/page/summary/{sci_name_url}'
                    resp = requests.get(url=url, headers=headers, timeout=10)
                    
                    # If scientific name fails, try common name
                    if resp.status_code != 200:
                        com_name_url = comName.replace(' ', '_')
                        url = f'https://en.wikipedia.org/api/rest_v1/page/summary/{com_name_url}'
                        resp = requests.get(url=url, headers=headers, timeout=10)
                    
                    resp.encoding = "utf-8"
                    data = resp.json()
                    
                    # Check if we have an image
                    if resp.status_code == 200 and 'originalimage' in data and 'source' in data['originalimage']:
                        image_url = data['originalimage']['source']
                    else:
                        image_url = ""
                        
                    flickr_images[comName] = image_url
                except Exception as e:
                    print("WIKIPEDIA API ERROR: "+str(e))
                    image_url = ""
            else:
                image_url = flickr_images[comName]

        if settings_dict.get('APPRISE_NOTIFY_EACH_DETECTION') == "1":
            notify_body = render_template(body, "detection")
            notify_title = render_template(title, "detection")
            notify(notify_body, notify_title, image_url)
            species_last_notified[comName] = int(timeim.time())

        APPRISE_NOTIFICATION_NEW_SPECIES_DAILY_COUNT_LIMIT = 1  # Notifies the first N per day.
        if settings_dict.get('APPRISE_NOTIFY_NEW_SPECIES_EACH_DAY') == "1":
            try:
                con = sqlite3.connect(db_path)
                cur = con.cursor()
                today = datetime.now().strftime("%Y-%m-%d")
                cur.execute(f"SELECT DISTINCT(Com_Name), COUNT(Com_Name) FROM detections WHERE Date = DATE('{today}') GROUP BY Com_Name")
                known_species = cur.fetchall()
                detections = [d[1] for d in known_species if d[0] == comName.replace("'", "")]
                numberDetections = 0
                if len(detections):
                    numberDetections = detections[0]
                if numberDetections > 0 and numberDetections <= APPRISE_NOTIFICATION_NEW_SPECIES_DAILY_COUNT_LIMIT:
                    print("send the notification")
                    notify_body = render_template(body, "first time today")
                    notify_title = render_template(title, "first time today")
                    notify(notify_body, notify_title, image_url)
                    species_last_notified[comName] = int(timeim.time())
                con.close()
            except sqlite3.Error as e:
                print(e)
                print("Database busy")
                timeim.sleep(2)

        if settings_dict.get('APPRISE_NOTIFY_NEW_SPECIES') == "1":
            try:
                con = sqlite3.connect(db_path)
                cur = con.cursor()
                today = datetime.now().strftime("%Y-%m-%d")
                cur.execute(f"SELECT DISTINCT(Com_Name), COUNT(Com_Name) FROM detections WHERE Date >= DATE('{today}', '-7 day') GROUP BY Com_Name")
                known_species = cur.fetchall()
                detections = [d[1] for d in known_species if d[0] == comName.replace("'", "")]
                numberDetections = 0
                if len(detections):
                    numberDetections = detections[0]
                if numberDetections > 0 and numberDetections <= 5:
                    reason = f"only seen {numberDetections} times in last 7d"
                    notify_body = render_template(body, reason)
                    notify_title = render_template(title, reason)
                    notify(notify_body, notify_title, image_url)
                    species_last_notified[comName] = int(timeim.time())
                con.close()
            except sqlite3.Error:
                print("Database busy")
                timeim.sleep(2)


if __name__ == "__main__":
    print("notfications")
