import os
from flask import Flask, render_template, request
from confluent_kafka import Consumer, KafkaError, TopicPartition
from confluent_kafka.admin import AdminClient
import json
import time
from datetime import datetime
import logging

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)

# Load Kafka configurations from environment variables
bootstrap_servers = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'abc:9092')  # Original Kafka Bootstrap Server
security_protocol = os.getenv('KAFKA_SECURITY_PROTOCOL', 'sasl_ssl')  # Original Kafka Authentication Protocol
sasl_mechanism = os.getenv('KAFKA_SASL_MECHANISM', 'PLAIN')           # Original Security Mechanism
sasl_username = os.getenv('KAFKA_SASL_USERNAME', 'ABCDEF')            # Original Cluster API KEY
sasl_password = os.getenv('KAFKA_SASL_PASSWORD', 'sbsbnbaj22w22nej')  # Original Cluster API Secret

admin_conf = {
    'bootstrap.servers': bootstrap_servers,
    'security.protocol': security_protocol,
    'sasl.mechanism': sasl_mechanism,
    'sasl.username': sasl_username,
    'sasl.password': sasl_password,
}

kafka_topics = []

def refresh_kafka_topics():       # Loads All Kafka Topics From the Cluster
    global kafka_topics
    admin_client = AdminClient(admin_conf)
    try:
        cluster_metadata = admin_client.list_topics(timeout=10)  # Waits for 10 seconds to get all the topics from the cluster
        kafka_topics = list(cluster_metadata.topics.keys())
    except Exception as e:
        logging.error("Failed to fetch Kafka topics: %s", e)
    finally:
        del admin_client

def search_kafka_topic(topic, filter_criteria=None, start_timestamp=None, end_timestamp=None):   # Queries inside the topic for relevant Data
    consumer_conf = {
        'bootstrap.servers': bootstrap_servers,
        'group.id': 'app-consumer-group',
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': False,   # Should be Kept False so that consumer group can query the same topic data Again
        'security.protocol': security_protocol,
        'sasl.mechanism': sasl_mechanism,
        'sasl.username': sasl_username,
        'sasl.password': sasl_password,
    }

    consumer = Consumer(consumer_conf)
    partitions = consumer.list_topics(topic, timeout=10).topics[topic].partitions.keys()   # Polls and waits for 10 seconds to get all data present in the topic
    consumer.assign([TopicPartition(topic, p, 0) for p in partitions])

    messages = []
    total_messages = 0
    filtered_messages = 0

    try:
        for p in partitions:
            tp = TopicPartition(topic, p)
            low, high = consumer.get_watermark_offsets(tp)
            total_messages += high - low

        timeout = time.time() + 10

        while time.time() < timeout:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                else:
                    logging.error("Consumer error: %s", msg.error())
                    break
            else:
                timestamp = datetime.utcfromtimestamp(msg.timestamp()[1] / 1000)  # Convert milliseconds to seconds
                value = msg.value().decode('utf-8') if msg.value() else None
                message = {
                    'topic': msg.topic(),
                    'partition': msg.partition(),
                    'offset': msg.offset(),
                    'timestamp': timestamp.strftime('%Y-%m-%d %H:%M:%S'),  # Format timestamp
                    'headers': msg.headers(),
                    'key': msg.key(),
                    'value': json.loads(value) if value else None
                }

                if filter_criteria:
                    try:
                        if eval(filter_criteria, {"message": message}):
                            messages.append(message)
                            filtered_messages += 1
                    except Exception as e:
                        logging.error("Error evaluating filter criteria: %s", e)
                elif start_timestamp and end_timestamp:
                    if start_timestamp <= timestamp.timestamp() <= end_timestamp:
                        messages.append(message)
                        filtered_messages += 1
                else:
                    messages.append(message)

    finally:
        consumer.close()

    return messages, total_messages, filtered_messages

@app.route('/')
def index():
    refresh_kafka_topics()
    return render_template('index.html', topics=kafka_topics)

@app.route('/search', methods=['POST'])
def search():
    topic = request.form['topic']
    filter_criteria = request.form.get('filter_criteria')
    start_timestamp_str = request.form.get('start_timestamp')
    end_timestamp_str = request.form.get('end_timestamp')

    start_timestamp = None
    end_timestamp = None

    if start_timestamp_str:
        start_timestamp = datetime.strptime(start_timestamp_str, '%Y-%m-%dT%H:%M').timestamp()

    if end_timestamp_str:
        end_timestamp = datetime.strptime(end_timestamp_str, '%Y-%m-%dT%H:%M').timestamp()

    messages, total_messages, filtered_messages = search_kafka_topic(topic, filter_criteria, start_timestamp, end_timestamp)

    # Assign sequential numbers to messages
    for i, message in enumerate(messages, start=1):
        message['number'] = i

    return render_template('search_results.html', topic=topic, messages=messages, total_messages=total_messages, filtered_messages=filtered_messages, start_timestamp=start_timestamp_str, end_timestamp=end_timestamp_str)

if __name__ == '__main__':
    app.run(debug=False)
