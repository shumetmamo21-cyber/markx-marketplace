-- MarkX database bootstrap. Run once per database, as a PostgreSQL superuser.
--
--   psql -v ON_ERROR_STOP=1 \
--        -v dbname=markx \
--        -v migrator_password=... -v app_password=... -v readonly_password=... \
--        -f infra/postgres/bootstrap.sql
--
-- It creates the three roles the blueprint requires (section F.3) and an empty
-- database. Tables come from Alembic migrations, never from this file.
--
--   markx_migrator  owns the schema; used only by migrations
--   markx_app       used by the API and the worker; reads and writes rows, but
--                   cannot change the schema and cannot rewrite history tables
--   markx_readonly  used for analysis; reads only
--
-- Safe to run again: every step checks before it acts.

select format('create role markx_migrator login password %L', :'migrator_password')
 where not exists (select from pg_roles where rolname = 'markx_migrator') \gexec
select format('create role markx_app login password %L', :'app_password')
 where not exists (select from pg_roles where rolname = 'markx_app') \gexec
select format('create role markx_readonly login password %L', :'readonly_password')
 where not exists (select from pg_roles where rolname = 'markx_readonly') \gexec

-- Keep passwords in step with the variables on a re-run.
select format('alter role markx_migrator password %L', :'migrator_password') \gexec
select format('alter role markx_app password %L', :'app_password') \gexec
select format('alter role markx_readonly password %L', :'readonly_password') \gexec

-- The built-in C.UTF-8 locale gives the same character rules on every host,
-- independent of the operating system's C library. Trigram matching on
-- Ethiopic text depends on it (docs/reports/trigram-ethiopic.md).
select format(
         'create database %I owner markx_migrator template template0 encoding ''UTF8'' '
         'locale_provider builtin builtin_locale ''C.UTF-8''',
         :'dbname')
 where not exists (select from pg_database where datname = :'dbname') \gexec

select format('revoke all on database %I from public', :'dbname') \gexec
select format('grant connect on database %I to markx_app, markx_readonly', :'dbname') \gexec

\connect :dbname

alter schema public owner to markx_migrator;
revoke all on schema public from public;
grant usage on schema public to markx_app, markx_readonly;

-- Every table the migrator creates from now on is readable and writable by the
-- application and readable by the analyst. Migrations then take rights away
-- from the tables that must only grow (audit log, ledger, history tables).
alter default privileges for role markx_migrator in schema public
  grant select, insert, update, delete on tables to markx_app;
alter default privileges for role markx_migrator in schema public
  grant usage, select on sequences to markx_app;
alter default privileges for role markx_migrator in schema public
  grant select on tables to markx_readonly;
