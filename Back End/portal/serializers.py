from rest_framework import serializers
from .models import Students, Applications, AcademicDetails, Documents

class StudentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Students
        fields = '__all__'

class AcademicDetailsSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicDetails
        fields = '__all__'

class ApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Applications
        fields = '__all__'

class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Documents
        fields = '__all__'