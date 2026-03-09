/*
 * Jenkinsfile — Nightly Regression Pipeline
 * 
 * This pipeline runs in two modes:
 *   1. ON EVERY COMMIT: Quick unit tests only (fast feedback)
 *   2. NIGHTLY (scheduled): Full regression — unit + integration + coverage
 *
 * To set up: In Jenkins, create a "Pipeline" job, point it to your repo,
 * and set "Script Path" to "Jenkinsfile".
 */

pipeline {
    agent {
        docker {
            image 'python:3.11-slim'
            args '-u root'
        }
    }

    // ── Nightly trigger: runs every night at 2 AM ──
    triggers {
        cron('H 2 * * *')
    }

    environment {
        PYTHONPATH = "${WORKSPACE}"
        PIP_NO_CACHE_DIR = "1"
    }

    options {
        timeout(time: 30, unit: 'MINUTES')
        timestamps()
        buildDiscarder(logRotator(numToKeepStr: '30'))
    }

    stages {

        // ── Stage 1: Setup ──
        stage('Setup') {
            steps {
                sh '''
                    python --version
                    pip install -r requirements.txt
                    mkdir -p reports
                '''
            }
        }

        // ── Stage 2: Lint (runs on every build) ──
        stage('Lint') {
            steps {
                sh '''
                    pip install flake8
                    flake8 sensor_pipeline/ --max-line-length=120 --count --statistics || true
                '''
            }
        }

        // ── Stage 3: Unit Tests (runs on every build — fast) ──
        stage('Unit Tests') {
            steps {
                sh '''
                    python -m pytest tests/ \
                        -m "not integration" \
                        -v \
                        --tb=short \
                        --junitxml=reports/unit-test-results.xml \
                        --html=reports/unit-test-report.html \
                        --self-contained-html
                '''
            }
            post {
                always {
                    junit 'reports/unit-test-results.xml'
                }
            }
        }

        // ── Stage 4: Integration Tests (NIGHTLY ONLY) ──
        stage('Integration Tests') {
            when {
                anyOf {
                    triggeredBy 'TimerTrigger'              // nightly cron
                    branch 'main'                            // merges to main
                    expression { params.RUN_FULL_REGRESSION == true }
                }
            }
            steps {
                sh '''
                    python -m pytest tests/ \
                        -m "integration" \
                        -v \
                        --tb=long \
                        --junitxml=reports/integration-test-results.xml \
                        --html=reports/integration-test-report.html \
                        --self-contained-html
                '''
            }
            post {
                always {
                    junit 'reports/integration-test-results.xml'
                }
            }
        }

        // ── Stage 5: Coverage Report (NIGHTLY ONLY) ──
        stage('Coverage') {
            when {
                anyOf {
                    triggeredBy 'TimerTrigger'
                    branch 'main'
                    expression { params.RUN_FULL_REGRESSION == true }
                }
            }
            steps {
                sh '''
                    python -m pytest tests/ \
                        --cov=sensor_pipeline \
                        --cov-report=html:reports/coverage-html \
                        --cov-report=xml:reports/coverage.xml \
                        --cov-fail-under=80
                '''
            }
            post {
                always {
                    publishHTML(target: [
                        reportDir: 'reports/coverage-html',
                        reportFiles: 'index.html',
                        reportName: 'Coverage Report'
                    ])
                }
            }
        }
    }

    // ── Post-build Actions ──
    post {
        success {
            echo '✅ All tests passed!'
        }
        failure {
            echo '❌ Tests failed — check reports for details.'
            // Uncomment to enable email notifications:
            // mail to: 'rohankunduru2.0@gmail.com',
            //      subject: "FAILED: ${env.JOB_NAME} #${env.BUILD_NUMBER}",
            //      body: "Check: ${env.BUILD_URL}"
        }
        always {
            archiveArtifacts artifacts: 'reports/**', allowEmptyArchive: true
            cleanWs()
        }
    }
}
