#!/usr/bin/env node
// Minimal allow-list gateway that sits between cloudflared and PRAgent.
// Only the paths GitHub and uptime probes need are forwarded, so the admin
// console never reaches the public internet through the tunnel.

const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");

const UPSTREAM_HOST = process.env.TUNNEL_UPSTREAM_HOST || "127.0.0.1";
const UPSTREAM_PORT = Number(process.env.TUNNEL_UPSTREAM_PORT || 8080);
const LISTEN_PORT = Number(process.env.TUNNEL_LISTEN_PORT || 8081);
const LISTEN_HOST = process.env.TUNNEL_LISTEN_HOST || "127.0.0.1";
const EXPOSE_ADMIN = process.env.TUNNEL_EXPOSE_ADMIN === "1";

// Exact paths (and their sub-paths) that may pass through the tunnel.
const ALLOW = [/^\/webhooks\/github$/, /^\/health$/];

const LOG_PATH = path.join(__dirname, "tunnel-access.log");

function allowed(pathname) {
  if (EXPOSE_ADMIN) return true;
  return ALLOW.some((re) => re.test(pathname));
}

function log(line) {
  const entry = new Date().toISOString() + " " + line + "\n";
  process.stdout.write(entry);
  fs.appendFile(LOG_PATH, entry, () => {});
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://gateway.invalid");
  const pathname = url.pathname;
  const started = Date.now();

  if (!allowed(pathname)) {
    log("DENY  " + req.method + " " + pathname + " ua=" + (req.headers["user-agent"] || "-"));
    res.writeHead(404, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: "not found" }));
    return;
  }

  const proxy = http.request(
    {
      host: UPSTREAM_HOST,
      port: UPSTREAM_PORT,
      method: req.method,
      path: req.url,
      headers: { ...req.headers, host: UPSTREAM_HOST + ":" + UPSTREAM_PORT },
    },
    (upstream) => {
      res.writeHead(upstream.statusCode || 502, upstream.headers);
      upstream.pipe(res);
      upstream.on("end", () => {
        log(
          "PASS  " + req.method + " " + pathname + " -> " + upstream.statusCode +
          " " + (Date.now() - started) + "ms event=" + (req.headers["x-github-event"] || "-")
        );
      });
    }
  );

  proxy.on("error", (err) => {
    log("ERROR " + req.method + " " + pathname + " " + err.message);
    if (!res.headersSent) {
      res.writeHead(502, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: "upstream unreachable" }));
    } else {
      res.end();
    }
  });

  req.pipe(proxy);
});

server.listen(LISTEN_PORT, LISTEN_HOST, () => {
  log(
    "gateway listening on http://" + LISTEN_HOST + ":" + LISTEN_PORT +
    " -> http://" + UPSTREAM_HOST + ":" + UPSTREAM_PORT +
    (EXPOSE_ADMIN ? " (admin exposed)" : " (allow-list: /webhooks/github, /health)")
  );
});
