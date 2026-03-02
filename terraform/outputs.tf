output "instance_id" {
  value = aws_instance.claws.id
}

output "public_ip" {
  value = aws_instance.claws.public_ip
}

output "ssh_command" {
  value = "ssh ec2-user@${aws_instance.claws.public_ip}"
}
