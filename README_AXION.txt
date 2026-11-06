
PlayRemove FUD — Python 3.14 ready
==================================
Works on Python 3.14 without MongoDB Atlas.
If Atlas SSL fails, bot uses local JSON in BOT_DB/.

Setup
-----
cd PlayRemove
pip install -U -r requirements.txt

set BOT_TOKEN=your_token
set ADMIN_IDS=7630091970
REM Mongo optional on 3.14:
REM set MONGO_URI=mongodb+srv://USER:PASS@cluster...

python bot.py

You should see:
  DB mode: LOCAL JSON ...
  or
  MongoDB: connected ...
  PlayRemove FUD started ...

APK build needs Java JDK 17+ on PATH (java -version).

Admin updates
-------------
/broadcast <msg>
/announce <msg>
/clearannounce
