# hermes-conversation-agent

<!-- docker compose stop -->

<!-- docker compose start -->

<!-- Just docker compose up — that's it. Everything runs inside Docker.

The only things you still need to do manually are:

Start your tunnel so Chatwoot can reach the backend:

npx localtunnel --port 5000 --subdomain shy-moles-cut
Set up Chatwoot (one-time, if not done):

Open http://localhost:3000
Run DB migrations: docker compose exec chatwoot bundle exec rails db:chatwoot_prepare
Create an inbox → create an agent bot → paste its token into 
.env
 as CHATWOOT_ACCESS_TOKEN
Set the bot's webhook URL to https://shy-moles-cut.loca.lt/webhook
After that, every time you want to run the project it's just:

docker compose up -d
npx localtunnel --port 5000 --subdomain shy-moles-cut
That's the full workflow. No python app.py needed. -->