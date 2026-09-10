# GPLv3 Community distribution; version and multi-platform digest are deliberate.
FROM neo4j:5.26.30-community@sha256:22ec5cd05a8cbb372fc4bed5e384c30bc75fd92504c72be4462039761b105f61

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -o 7474 -g 7474 -m 0700 /automator-secrets \
    && install -d -o root -g root -m 0755 /opt/automator-neo4j
COPY --chown=root:root bootstrap.py healthcheck.py import_projection.py /opt/automator-neo4j/
# No credential exists at build time. Compile a fixed stdin bridge using the
# bundled JDK and Neo4j classes, rather than exposing the password in CLI argv.
RUN cd /opt/automator-neo4j \
    && python3 -c 'import bootstrap; bootstrap.build_helper("/opt/automator-neo4j")' \
    && chmod 0444 /opt/automator-neo4j/*.py /opt/automator-neo4j/*.class

USER neo4j
ENTRYPOINT ["tini", "-g", "--", "python3", "/opt/automator-neo4j/bootstrap.py"]
CMD []
