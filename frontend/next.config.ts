import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  // Link-preview crawlers that need metadata in <head> (no JS). The default list has WhatsApp but not Telegram.
  htmlLimitedBots:
    /facebookexternalhit|facebookcatalog|Twitterbot|LinkedInBot|Slackbot|Discordbot|WhatsApp|TelegramBot|SkypeUriPreview|redditbot|applebot|Bingbot|BingPreview|[\w-]+-Google|Google-[\w-]+|DuckDuckBot|yandex|vkShare|Pinterest/i,
};

export default nextConfig;
