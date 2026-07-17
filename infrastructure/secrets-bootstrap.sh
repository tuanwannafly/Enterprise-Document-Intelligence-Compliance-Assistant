# AWS Secrets Manager — bootstrap commands

# Set up the DB secret (host/port/user/password/database connection string).
aws secretsmanager create-secret \
    --name edi-compliance/db \
    --description "Postgres connection string for the EDI compliance service" \
    --secret-string '{
        "host": "edi-compliance-postgres.xxxxx.us-east-1.rds.amazonaws.com",
        "port": 5432,
        "database": "edi",
        "username": "edi_owner",
        "password": "REPLACE_ME"
    }' \
    --tags Key=Project,Value=edi-compliance Key=Env,Value=production

# Set up the Cognito secret (user pool id, app client id, JWKS URL).
aws secretsmanager create-secret \
    --name edi-compliance/cognito \
    --description "Cognito User Pool config for the EDI compliance service" \
    --secret-string '{
        "COGNITO_USER_POOL_ID": "us-east-1_xxxxx",
        "COGNITO_APP_CLIENT_ID": "xxxxxxxxxxxxxxxxxxxxxxxxxx",
        "COGNITO_JWKS_URL": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_xxxxx/.well-known/jwks.json"
    }' \
    --tags Key=Project,Value=edi-compliance Key=Env,Value=production
