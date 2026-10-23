import com.apismith.instagram.transcriptapi.ClientConfig;
import com.apismith.instagram.transcriptapi.CsvPlan;
import com.apismith.instagram.transcriptapi.InputValidators;
import java.math.BigDecimal;

/** Compiled outside the SDK package against the freshly built shaded artifact. */
public final class ExternalConsumer {
    public static void main(String[] args) {
        String url = InputValidators.validateVideoUrl(
                "https://www.instagram.com/reel/ConsumerCheck123/");
        if (!url.endsWith("/ConsumerCheck123/")) {
            throw new AssertionError("public URL validation returned an unexpected value");
        }

        ClientConfig config = ClientConfig.builder()
                .token("synthetic-consumer-test-value")
                .requireChargeCap(true)
                .maxTotalChargeUsd(new BigDecimal("0.10"))
                .build();
        if (!config.requireChargeCap()
                || config.maxTotalChargeUsd().compareTo(new BigDecimal("0.10")) != 0
                || !ClientConfig.CONTROLLED_BUILD_NUMBER.equals(config.buildNumber())) {
            throw new AssertionError("public ClientConfig API returned unexpected settings");
        }

        CsvPlan plan = new CsvPlan("csv_batch_plan", 2, 2, 1,
                ClientConfig.CONTROLLED_BUILD_NUMBER, true, new BigDecimal("0.10"),
                new BigDecimal("0.20"), "consumer.csv");
        if (plan.maximumActorRuns() != 2 || plan.estimatedMaximumRunCapsTotalUsd()
                .compareTo(new BigDecimal("0.20")) != 0) {
            throw new AssertionError("public CsvPlan API returned unexpected values");
        }

        System.out.println("External shaded-JAR consumer: PASS");
    }
}
