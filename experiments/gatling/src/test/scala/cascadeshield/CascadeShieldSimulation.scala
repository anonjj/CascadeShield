package cascadeshield

import io.gatling.core.Predef._
import io.gatling.http.Predef._
import scala.concurrent.duration._

class CascadeShieldSimulation extends Simulation {

  // All parameters are env-var driven so runner.py can call this without code changes.
  val baseUrl   = sys.env.getOrElse("GATEWAY_URL", "http://localhost:8080")
  val tps       = sys.env.getOrElse("GATLING_TPS", "20").toInt
  val durationS = sys.env.getOrElse("GATLING_DURATION_S", "60").toInt
  val topology  = sys.env.getOrElse("GATLING_TOPOLOGY", "linear")
  val profile   = sys.env.getOrElse("GATLING_PROFILE", "sustained")

  val httpProtocol = http
    .baseUrl(baseUrl)
    .acceptHeader("application/json")
    .disableFollowRedirect

  // Single scenario — both profiles share the same request definition.
  // 503 is accepted: circuit breakers produce 503 under fault; failing on it
  // would abort the simulation before the measurement window completes.
  val scn = scenario("CascadeShield")
    .exec(
      http(s"GET /api/v1/$topology")
        .get(s"/api/v1/$topology")
        .check(status.in(200, 503))
    )

  val sustainedInjection = scn.inject(
    rampUsersPerSec(1).to(tps).during(10.seconds),
    constantUsersPerSec(tps).during(durationS.seconds)
  )

  // Bursty: spike at 3× TPS to saturate sliding window fast, then settle.
  // Used for the Window×Traffic sub-study in Week 3+.
  val burstyInjection = scn.inject(
    nothingFor(5.seconds),
    atOnceUsers(tps * 3),
    nothingFor(10.seconds),
    constantUsersPerSec(tps).during(durationS.seconds)
  )

  val injection = if (profile == "bursty") burstyInjection else sustainedInjection

  setUp(injection)
    .protocols(httpProtocol)
    // Soft assertion: don't fail the batch on latency spikes under fault injection.
    .assertions(global.responseTime.max.lt(10000))
}
