FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /build
# Build context is the repo root (see infra/docker-compose.yml) so this stage can see the
# shared cascadeshield-parent/cascadeshield-common modules -- mirror the source tree
# exactly so their <relativePath> references resolve unchanged.
COPY cascadeshield-parent/pom.xml cascadeshield-parent/pom.xml
# Installs the parent POM's descriptor into this stage's local repo. Required, not just
# nice-to-have: cascadeshield-common's <relativePath> resolves it fine for common's OWN
# build below, but once common is itself installed and later read back as a plain
# dependency (by services/inventory-service/pom.xml's dependency resolution), Maven looks up
# common's parent by GAV coordinates in the local/remote repo, not by relativePath --
# without this install step that lookup fails against Maven Central.
RUN mvn -f cascadeshield-parent/pom.xml install -N -q
COPY cascadeshield-common/pom.xml cascadeshield-common/pom.xml
COPY cascadeshield-common/src cascadeshield-common/src
RUN mvn -f cascadeshield-common/pom.xml install -q -DskipTests
COPY services/inventory-service/pom.xml services/inventory-service/pom.xml
RUN mvn -f services/inventory-service/pom.xml dependency:go-offline -q
COPY services/inventory-service/src services/inventory-service/src
RUN mvn -f services/inventory-service/pom.xml package -DskipTests -q

FROM eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /build/services/inventory-service/target/*.jar app.jar
EXPOSE 8082
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]
