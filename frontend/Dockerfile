FROM node:26-slim

# install pnpm directly (avoids corepack/node version mismatches)
RUN npm install -g pnpm@9

WORKDIR /app
COPY . ./
RUN pnpm install --no-frozen-lockfile

EXPOSE 3000
# dev server (no build-time prerender; reads TRACELY_API at request time)
CMD ["pnpm", "exec", "next", "dev", "-H", "0.0.0.0"]
