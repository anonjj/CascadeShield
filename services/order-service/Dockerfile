FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /build
# Build context is the repo root (see infra/docker-compose.yml) so this stage can see the
# shared cascadeshield-parent POM -- mirror the source tree exactly so its
# <relativePath>../../cascadeshield-parent/pom.xml</relativePath> resolves unchanged.
COPY cascadeshield-parent/pom.xml cascadeshield-parent/pom.xml
COPY services/order-service/pom.xml services/order-service/pom.xml
RUN mvn -f services/order-service/pom.xml dependency:go-offline -q
COPY services/order-service/src services/order-service/src
RUN mvn -f services/order-service/pom.xml package -DskipTests -q

FROM eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /build/services/order-service/target/*.jar app.jar
EXPOSE 8081
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]
