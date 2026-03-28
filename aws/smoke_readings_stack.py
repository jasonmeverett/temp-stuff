from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_apigatewayv2_integrations as apigwv2_integrations
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_lambda as lambda_
from constructs import Construct


class SmokeReadingsStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        table = dynamodb.Table(
            self,
            "ReadingsTable",
            partition_key=dynamodb.Attribute(
                name="smoke_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True,
            ),
        )

        fn = lambda_.Function(
            self,
            "TelemetryFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset("lambda"),
            timeout=Duration.seconds(10),
            environment={"TABLE_NAME": table.table_name},
        )

        table.grant_read_write_data(fn)

        http_api = apigwv2.HttpApi(
            self,
            "TelemetryHttpApi",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_headers=["Content-Type"],
                allow_methods=[
                    apigwv2.CorsHttpMethod.GET,
                    apigwv2.CorsHttpMethod.POST,
                    apigwv2.CorsHttpMethod.OPTIONS,
                ],
                allow_origins=["*"],
            ),
        )

        integration = apigwv2_integrations.HttpLambdaIntegration(
            "TelemetryIntegration",
            fn,
        )
        http_api.add_routes(
            path="/telemetry",
            methods=[apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
            integration=integration,
        )

        self.table = table
        self.telemetry_function = fn
        self.http_api = http_api

        CfnOutput(self, "TelemetryApiUrl", value=http_api.api_endpoint)
        CfnOutput(self, "ReadingsTableName", value=table.table_name)
