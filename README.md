# Devops-Assistant
## To run the flask app:
* create a .env file with the help of sample env.txt
* do ` pip install -r requirements.txt `
* run app.py
* type ngrok http 5000 in cmd and copy the url mentioned
* at the end of your Jenkinsfile, add: 
```
post {
    failure {
        script {
            bat 'curl -X POST https://your-ngrok-url/webhook/jenkins'
            }
        }
    }
```

* go to jenkins and run the build (failed build)
* you will then see the results in email
