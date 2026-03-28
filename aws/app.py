#!/usr/bin/env python3

import aws_cdk as cdk

from smoke_readings_stack import SmokeReadingsStack


app = cdk.App()
SmokeReadingsStack(app, "SmokeReadingsStack")
app.synth()
