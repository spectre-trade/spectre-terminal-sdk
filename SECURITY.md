# Security

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's
private vulnerability reporting on this repository ("Security" → "Report a
vulnerability"). You will get an acknowledgement within three working days.

## What counts

The clients talk to a terminal on the same machine with a bearer token that
grants read access to market data and the list of exchange connections. We
treat as security issues, among others:

- the token leaking into logs, error messages, crash reports or files written
  by a client;
- a client accepting a token from anywhere other than the environment
  variable or the explicit constructor argument (for example, reading the
  terminal's database);
- a client talking to any host other than `127.0.0.1`/`localhost`, or
  following redirects off the loopback interface;
- a dependency with a known vulnerability on the import path of a client.

The terminal itself (the Local API server) is a separate product; reports
about it are forwarded to the terminal team.
