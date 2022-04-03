# Posterity

#### Mission statement

We built this tool to allow people to archive videos related to the invasion of Ukraine. We believe anything that might help to document the atrocities and war crimes should be public domain.

We do not own the rights to any of this media. This software is self-contained and can be redeployed anywhere, all the data archived is mirrored on several locations. Please direct any DMCA claims or complaints to /dev/null.

All the code written for this is also public domain, so we encourage anyone to set up their own Posterity service for other topics. We also encourage people to  [help seed our torrents and Syncthing folder](https://posterity.no/download_archive)  to ensure the data persists.

#### Get involved

This is not a group or an organization, we do not accept donations. Anyone can contribute to the project but if you're really looking to help Ukraine you should donate your time and resources elsewhere.

-   [GitHub: Posterity](https://github.com/NiclasEriksen/posterity/). The GitHub repository for the code that this service is running. Submit issues, feature requests or pull requests here.
-   [GitHub: FeedBot](https://github.com/NiclasEriksen/Feedbot/). The GitHub repository for a Discord bot that posts videos to Posterity.
-   Add videos through the Discord bot, request a registration token for a contributor account or get in touch for API keys to post videos.
-   [Seed our torrents and/or add the Syncthing folder](https://posterity.no/download_archive). This is our safety in case we're taken offline.
-   Write us at  [shit@putin.no](mailto:shit@putin.no)  for any questions

#### Components used

-   [Flask](https://flask.palletsprojects.com/en/2.0.x/) web server
-   [SQLAlchemy](https://www.sqlalchemy.org/) ORM
-   [Redis Cache](https://redis.io/) cache/queue
-   [ffmpeg](https://ffmpeg.org/) the legwork
-   [youtube-dlc](https://github.com/blackjack4494/youtube-dlc) extract links
-   [Pillow](https://pillow.readthedocs.io/en/stable/) generate thumbnails
-   [ElasticSearch](https://www.elastic.co/elasticsearch/) search engine
-   [UIKit](https://getuikit.com/) CSS framework

#### Encoding settings

-   Everything is single-pass
-   Deinterlacing  enabled
-   Normalized audio
    -   Technique dynaudnorm
    -   Bit rate VBR
    -   Peak 85%
-   Downmix to stereo
-   Subtitles soft (container)