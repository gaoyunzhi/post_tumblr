#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import yaml
import time
import plain_db
import webgram
import post_2_album
from telegram_util import removeOldFiles, matchKey
import random
from bs4 import BeautifulSoup
import cached_url
import telepost
import pytumblr

with open('credential') as f:
    credential = yaml.load(f, Loader=yaml.FullLoader)

existing = plain_db.loadLargeDB('existing', isIntValue=False)

client = pytumblr.TumblrRestClient(
    credential['consumer_key'],
    credential['consumer_secret'],
    credential['token'],
    credential['token_secret'],
)

Day = 24 * 60 * 60

def getCutoffTime(channel):
    return time.time() - credential['channels'][channel]['padding_days'] * Day

def getRawPosts(channel):
    start = time.time()
    result = []
    posts = webgram.getPosts(channel)[1:]
    result += posts
    while posts and posts[0].time > (time.time() - 
            credential['channels'][channel]['back_days'] * Day):
        pivot = posts[0].post_id
        posts = webgram.getPosts(channel, posts[0].post_id, 
            direction='before')[1:]
        result += posts
    if random.random() > 0.2:
        random.shuffle(result)
    else:
        result = result[::-1]
    return result

def getPosts(channel):
    result = getRawPosts(channel)
    cutoff_time = getCutoffTime(channel)
    for post in result:
        if post.time > cutoff_time:
            continue
        try:
            yield post_2_album.get('https://t.me/' + post.getKey()), post
        except Exception as e:
            print('post_tumblr post_2_album failed', post.getKey(), str(e))

async def post_tumblr(tumblr_user, channel, post, album, status_text):
    if album.video:
        fns = await telepost.getImages(channel, post.post_id, post.getImgNumber())
        return client.create_video(tumblr_user, caption=status_text, data=fns)
    if album.imgs:    
        fns = await telepost.getImages(channel, post.post_id, post.getImgNumber())
        return client.create_photo(tumblr_user, caption=status_text, data=fns)
    return client.create_text(status_text)

async def runImp():
    removeOldFiles('tmp', day=0.1)
    channels = list(credential['channels'].keys())
    random.shuffle(channels)
    for channel in channels:
        for album, post in getPosts(channel):
            if existing.get(album.url):
                continue
            status_text = album.cap_html
            if not status_text:
                continue
            tumblr_user = credential['channels'][channel]['tumblr_user']
            result = await post_tumblr(tumblr_user, channel, post, album, status_text)
            print(album.url, result)
            result_url = 'https://tumblr.com/%s/%d' % (tumblr_user, result['id'])
            print(result_url)
            existing.update(album.url, result_url)
            return # only send one item for each run

async def run():
    await runImp()
    await telepost.exitTelethon()
        
if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run())
    loop.close()